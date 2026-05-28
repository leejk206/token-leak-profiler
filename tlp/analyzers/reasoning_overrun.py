from __future__ import annotations
import re
from datasketch import MinHash, MinHashLSH
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding
from tlp.tokenizer import count_tokens

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _ngrams(text: str, n: int) -> list[bytes]:
    text = text.lower()
    if len(text) < n:
        return [text.encode("utf-8")] if text else []
    return [text[i:i + n].encode("utf-8") for i in range(len(text) - n + 1)]


def _minhash(text: str, n: int, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for g in _ngrams(text, n):
        m.update(g)
    return m


class ReasoningOverrunAnalyzer(BaseAnalyzer):
    name = "reasoning_overrun"
    lever = LeverCategory.REASONING_OVERRUN
    usage_bucket = "output"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("reasoning_overrun", {})
        ratio = float(c.get("thinking_to_output_ratio", 5))
        ngram = int(c.get("sentence_ngram", 5))
        jacc_t = float(c.get("jaccard_threshold", 0.85))
        num_perm = 128

        findings: list[Finding] = []
        total = 0

        for ti, turn in enumerate(trace.turns):
            if turn.role != "assistant":
                continue
            thinking_tokens = sum(b.tokens for b in turn.blocks if b.kind == "thinking")
            text_tokens = sum(b.tokens for b in turn.blocks if b.kind == "text")
            if thinking_tokens == 0:
                continue

            # Overrun: thinking >> text
            overrun = 0
            if thinking_tokens > ratio * max(text_tokens, 1):
                overrun = thinking_tokens - int(ratio * max(text_tokens, 1))

            # Redundant sentences within thinking
            dup_tokens = 0
            dup_pairs: list[tuple[str, str, float]] = []
            sents: list[str] = []
            for b in turn.blocks:
                if b.kind == "thinking" and b.text:
                    sents.extend(s.strip() for s in _SENTENCE_SPLIT.split(b.text) if s.strip())
            if len(sents) >= 2:
                lsh = MinHashLSH(threshold=jacc_t, num_perm=num_perm)
                sigs: dict[int, MinHash] = {}
                for i, s in enumerate(sents):
                    m = _minhash(s, ngram, num_perm)
                    sigs[i] = m
                    lsh.insert(str(i), m)
                seen: set[tuple[int, int]] = set()
                for i, s in enumerate(sents):
                    for cand in lsh.query(sigs[i]):
                        j = int(cand)
                        if j == i:
                            continue
                        pair = (min(i, j), max(i, j))
                        if pair in seen:
                            continue
                        seen.add(pair)
                        jacc = sigs[i].jaccard(sigs[j])
                        if jacc >= jacc_t:
                            # Charge tokens of the later sentence
                            later = sents[max(i, j)]
                            dup_tokens += count_tokens(later)
                            dup_pairs.append((sents[min(i, j)][:60], later[:60], round(jacc, 2)))

            leak = overrun + dup_tokens
            if leak <= 0:
                continue
            total += leak
            findings.append(Finding(
                location=f"turn[{ti}]",
                leaked_tokens=leak,
                confidence="mid",
                suggestion=(
                    f"thinking={thinking_tokens} tok vs output={text_tokens} tok, "
                    f"{len(dup_pairs)} duplicate sentence pair(s) — lower max_thinking_tokens"
                ),
                evidence={
                    "thinking_tokens": thinking_tokens,
                    "output_tokens": text_tokens,
                    "overrun_tokens": overrun,
                    "duplicate_pairs": dup_pairs[:5],
                },
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
