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
            tool_use_tokens = sum(b.tokens for b in turn.blocks if b.kind == "tool_use")
            has_thinking_block = any(b.kind == "thinking" for b in turn.blocks)

            # Redacted thinking: blocks exist but content is server-encrypted (empty text + signature).
            # The tokens are still billed in usage.output_tokens, so back them out from the delta.
            thinking_redacted = False
            if thinking_tokens == 0 and has_thinking_block and turn.usage:
                estimated = turn.usage.output_tokens - text_tokens - tool_use_tokens
                if estimated > 0:
                    thinking_tokens = estimated
                    thinking_redacted = True

            if thinking_tokens == 0:
                continue

            # Overrun: thinking >> productive output. Tool calls are productive
            # output (an Edit/Bash/Write is a real action), so include them in
            # the denominator. Without this, every tool-only response trips this
            # lever regardless of how reasonable the thinking-to-action ratio is.
            productive_output = text_tokens + tool_use_tokens
            overrun = 0
            if thinking_tokens > ratio * max(productive_output, 1):
                overrun = thinking_tokens - int(ratio * max(productive_output, 1))

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
            # Distinguish *measured* leak (duplicate sentence pairs in visible
            # thinking) from *signal* (high thinking/output ratio with content
            # we can't see). The ratio alone doesn't prove waste — the thinking
            # may have been useful and unobservable. Surface ratio-only findings
            # at "low" so the default --min-confidence=mid filter hides them
            # from the headline number while keeping them visible on demand.
            if dup_tokens > 0:
                confidence = "mid"
            else:
                confidence = "low"
            est_note = " (estimated from usage delta, content not visible)" if thinking_redacted else ""
            findings.append(Finding(
                location=f"turn[{ti}]",
                leaked_tokens=leak,
                confidence=confidence,
                suggestion=(
                    f"thinking={thinking_tokens} tok{est_note} vs productive={productive_output} tok "
                    f"(text={text_tokens}, tool_use={tool_use_tokens}), "
                    f"{len(dup_pairs)} duplicate sentence pair(s) — lower max_thinking_tokens"
                ),
                evidence={
                    "thinking_tokens": thinking_tokens,
                    "text_tokens": text_tokens,
                    "tool_use_tokens": tool_use_tokens,
                    "productive_output_tokens": productive_output,
                    "overrun_tokens": overrun,
                    "duplicate_pairs": dup_pairs[:5],
                    "thinking_redacted": thinking_redacted,
                },
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
