from __future__ import annotations
from datasketch import MinHash, MinHashLSH
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


def _ngrams(text: str, n: int = 5) -> list[bytes]:
    text = text.lower()
    if len(text) < n:
        return [text.encode("utf-8")] if text else []
    return [text[i:i + n].encode("utf-8") for i in range(len(text) - n + 1)]


def _minhash(text: str, n: int, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for g in _ngrams(text, n):
        m.update(g)
    return m


class RedundantRestatementAnalyzer(BaseAnalyzer):
    name = "redundant_restatement"
    lever = LeverCategory.REDUNDANT_RESTATEMENT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("redundant_restatement", {})
        threshold = float(c.get("jaccard_threshold", 0.8))
        ngram = int(c.get("ngram", 5))
        num_perm = int(c.get("num_perm", 256))

        # Collect (turn_index, block_index, text, tokens)
        items: list[tuple[int, int, str, int]] = []
        for ti, turn in enumerate(trace.turns):
            for bi, b in enumerate(turn.blocks):
                if b.kind != "text" or not b.text or b.tokens < 20:
                    continue
                items.append((ti, bi, b.text, b.tokens))

        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        sigs: dict[str, MinHash] = {}
        for ti, bi, text, _ in items:
            key = f"turn[{ti}].blocks[{bi}]"
            m = _minhash(text, ngram, num_perm)
            sigs[key] = m
            lsh.insert(key, m)

        seen_pairs: set[tuple[str, str]] = set()
        findings: list[Finding] = []
        total = 0
        for ti, bi, text, tokens in items:
            key = f"turn[{ti}].blocks[{bi}]"
            candidates = [c for c in lsh.query(sigs[key]) if c != key]
            for cand in candidates:
                pair = tuple(sorted((key, cand)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                jacc = sigs[key].jaccard(sigs[cand])
                if jacc < threshold:
                    continue
                # Flag the later occurrence
                later, earlier = (key, cand) if _turn_idx(key) > _turn_idx(cand) else (cand, key)
                later_tokens = next(t for ti2, bi2, _, t in items if f"turn[{ti2}].blocks[{bi2}]" == later)
                total += later_tokens
                findings.append(Finding(
                    location=later, leaked_tokens=later_tokens,
                    confidence="high" if jacc >= 0.95 else "mid",
                    suggestion=f"near-duplicate of {earlier} (jaccard={jacc:.2f}) — drop or move to system prompt",
                    evidence={"duplicate_of": earlier, "jaccard": round(jacc, 3)},
                    evidence_kind="confirmed",
                ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )


def _turn_idx(loc: str) -> int:
    return int(loc.split("[")[1].split("]")[0])
