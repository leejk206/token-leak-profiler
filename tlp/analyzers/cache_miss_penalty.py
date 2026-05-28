from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class CacheMissPenaltyAnalyzer(BaseAnalyzer):
    name = "cache_miss_penalty"
    lever = LeverCategory.CACHE_MISS_PENALTY
    usage_bucket = "cache_creation"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("cache_miss_penalty", {})
        min_recreation_turns = int(c.get("min_recreation_turns", 3))
        min_avg_creation_tokens = int(c.get("min_avg_creation_tokens", 1000))

        # Skip turn 0 (initial cache build is unavoidable) and any turn without usage.
        affected: list[tuple[int, int]] = []  # (turn_index, cache_creation_tokens)
        first_assistant_seen = False
        for ti, turn in enumerate(trace.turns):
            if turn.role != "assistant" or turn.usage is None:
                continue
            if not first_assistant_seen:
                first_assistant_seen = True
                continue  # excluded baseline
            if turn.usage.cache_creation_tokens > 0:
                affected.append((ti, turn.usage.cache_creation_tokens))

        if len(affected) < min_recreation_turns:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        total = sum(tok for _, tok in affected)
        mean = total // len(affected)
        if mean < min_avg_creation_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        confidence = "high" if mean >= 5000 else "mid"
        finding = Finding(
            location="session",
            leaked_tokens=total,
            confidence=confidence,
            suggestion=(
                f"{len(affected)} turns recreated cache (avg {mean} tok each). "
                f"Likely cause: dynamic content at context tail. Check for timestamps, "
                f"counters, or session-meta appended after stable system prompt."
            ),
            evidence={
                "affected_turn_count": len(affected),
                "mean_creation_tokens": mean,
                "total_creation_tokens": total,
                "affected_turn_indexes": [ti for ti, _ in affected][:20],
            },
            evidence_kind="confirmed",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=[finding],
        )
