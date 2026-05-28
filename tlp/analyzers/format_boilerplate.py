from __future__ import annotations
from collections import Counter
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding
from tlp.tokenizer import count_tokens


def _common_prefix(strings: list[str]) -> str:
    if not strings:
        return ""
    s_min = min(strings, key=len)
    for i, ch in enumerate(s_min):
        for s in strings:
            if s[i] != ch:
                return s_min[:i]
    return s_min


def _common_suffix(strings: list[str]) -> str:
    rev = [s[::-1] for s in strings]
    return _common_prefix(rev)[::-1]


class FormatBoilerplateAnalyzer(BaseAnalyzer):
    name = "format_boilerplate"
    lever = LeverCategory.FORMAT_BOILERPLATE
    usage_bucket = "output"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("format_boilerplate", {})
        window_tokens = int(c.get("edge_window_tokens", 80))
        min_rep = int(c.get("min_repetition", 3))
        window_chars = window_tokens * 4  # inverse of chars/4

        # Collect assistant text blocks
        texts: list[tuple[int, int, str]] = []  # (turn_idx, block_idx, text)
        for ti, t in enumerate(trace.turns):
            if t.role != "assistant":
                continue
            for bi, b in enumerate(t.blocks):
                if b.kind == "text" and b.text:
                    texts.append((ti, bi, b.text))

        if len(texts) < min_rep:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        findings: list[Finding] = []
        total = 0

        # Prefix patterns: count distinct first-K-char prefixes
        prefix_buckets: Counter[str] = Counter()
        suffix_buckets: Counter[str] = Counter()
        for _, _, txt in texts:
            head = txt[:window_chars]
            tail = txt[-window_chars:]
            # Bucket by first 40 chars to group similar starts before doing LCS
            prefix_buckets[head[:40]] += 1
            suffix_buckets[tail[-40:]] += 1

        # Find groups with >= min_rep
        for pseed, cnt in prefix_buckets.items():
            if cnt < min_rep:
                continue
            group = [txt for _, _, txt in texts if txt.startswith(pseed)]
            common = _common_prefix(group)
            if not common.strip():
                continue
            tokens_each = count_tokens(common)
            if tokens_each == 0:
                continue
            extra_reps = cnt - 1  # first occurrence is "free"
            leak = tokens_each * extra_reps
            total += leak
            example_locs = [
                f"turn[{ti}].blocks[{bi}]"
                for ti, bi, txt in texts if txt.startswith(pseed)
            ][:3]
            findings.append(Finding(
                location=f"prefix_group({example_locs[0]}+{extra_reps})",
                leaked_tokens=leak,
                confidence="high" if cnt >= 5 else "mid",
                suggestion=(
                    f"prefix '{common.strip()[:40]}...' repeated {cnt}x — "
                    f"add 'no preamble' instruction to system prompt or use stop sequence"
                ),
                evidence={"pattern": common, "repetitions": cnt, "locations": example_locs},
            ))

        for sseed, cnt in suffix_buckets.items():
            if cnt < min_rep:
                continue
            group = [txt for _, _, txt in texts if txt.endswith(sseed)]
            common = _common_suffix(group)
            if not common.strip():
                continue
            tokens_each = count_tokens(common)
            if tokens_each == 0:
                continue
            extra_reps = cnt - 1
            leak = tokens_each * extra_reps
            total += leak
            example_locs = [
                f"turn[{ti}].blocks[{bi}]"
                for ti, bi, txt in texts if txt.endswith(sseed)
            ][:3]
            findings.append(Finding(
                location=f"suffix_group({example_locs[0]}+{extra_reps})",
                leaked_tokens=leak,
                confidence="high" if cnt >= 5 else "mid",
                suggestion=(
                    f"suffix '{common.strip()[-40:]}' repeated {cnt}x — "
                    f"add 'no trailing summary' instruction or stop sequence"
                ),
                evidence={"pattern": common, "repetitions": cnt, "locations": example_locs},
            ))

        findings.sort(key=lambda f: f.leaked_tokens, reverse=True)
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
