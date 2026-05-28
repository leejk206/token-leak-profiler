from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import (
    LeverCategory, LeakReport, ParsedTrace, Finding,
)


def _ngrams(text: str, n: int = 3) -> set[str]:
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


class StaleContextAnalyzer(BaseAnalyzer):
    name = "stale_context"
    lever = LeverCategory.STALE_CONTEXT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        stale_after = int(config.get("stale_context", {}).get("stale_after_turns", 5))
        findings: list[Finding] = []
        total = 0

        # Precompute later-turn n-gram sets
        later_ngrams: list[set[str]] = [set()] * len(trace.turns)
        for i, turn in enumerate(trace.turns):
            joined = " ".join(b.text or "" for b in turn.blocks if b.kind in ("text", "tool_result", "thinking"))
            later_ngrams[i] = _ngrams(joined)

        for i, turn in enumerate(trace.turns):
            for bi, block in enumerate(turn.blocks):
                if block.kind not in ("text", "tool_result"):
                    continue
                if not block.text:
                    continue
                block_ngrams = _ngrams(block.text)
                if not block_ngrams:
                    continue
                last_ref = i
                for j in range(i + 1, len(trace.turns)):
                    # Require non-trivial overlap (>5 shared 3-grams) to count as reference
                    if len(block_ngrams & later_ngrams[j]) > 5:
                        last_ref = j
                # Number of turns the block kept living in context past its last reference
                trailing = len(trace.turns) - 1 - last_ref
                if trailing >= stale_after:
                    total += block.tokens
                    findings.append(Finding(
                        location=f"turn[{i}].blocks[{bi}]",
                        leaked_tokens=block.tokens,
                        confidence="mid",
                        suggestion=(
                            f"turn[{i}] block last referenced at turn[{last_ref}] "
                            f"({trailing} turns ago) — compress or drop"
                        ),
                        evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
                        evidence_kind="confirmed",
                    ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
