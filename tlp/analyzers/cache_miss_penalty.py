from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class CacheMissPenaltyAnalyzer(BaseAnalyzer):
    """Detect real prompt-cache invalidation.

    Healthy multi-turn conversations always have cache_creation > 0 — the new
    tail content (assistant output + tool_result) is cached for future reuse.
    A leak is when an EXISTING cached prefix is invalidated and has to be
    re-cached. We detect this by comparing observed `cache_read` against the
    value expected from continuity: `prev.cache_read + prev.cache_creation`.

    When `actual < expected` by a non-trivial margin, the gap represents
    tokens we paid the expensive `cache_creation` rate to re-cache instead of
    the cheap `cache_read` rate.
    """

    name = "cache_miss_penalty"
    lever = LeverCategory.CACHE_MISS_PENALTY
    usage_bucket = "cache_creation"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("cache_miss_penalty", {})
        min_drop = int(c.get("min_invalidation_drop", 5000))

        # Collect assistant turns with usage in document order
        usages: list[tuple[int, int, int]] = []  # (turn_index, cache_read, cache_creation)
        for ti, turn in enumerate(trace.turns):
            if turn.role != "assistant" or turn.usage is None:
                continue
            usages.append((ti, turn.usage.cache_read_tokens, turn.usage.cache_creation_tokens))

        if len(usages) < 2:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        invalidations: list[tuple[int, int]] = []  # (turn_index, drop_tokens)
        for i in range(1, len(usages)):
            ti, cr, _ = usages[i]
            prev_ti, prev_cr, prev_cc = usages[i - 1]
            expected_cr = prev_cr + prev_cc
            drop = expected_cr - cr
            if drop >= min_drop:
                invalidations.append((ti, drop))

        if not invalidations:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        total = sum(drop for _, drop in invalidations)
        count = len(invalidations)
        mean = total // count

        if count >= 5 or total > 50_000:
            confidence = "high"
        elif count >= 2:
            confidence = "mid"
        else:
            confidence = "low"

        finding = Finding(
            location="session",
            leaked_tokens=total,
            confidence=confidence,
            suggestion=(
                f"{count} turn(s) showed prefix invalidation (avg {mean} tok dropped per "
                f"event). Likely cause: system-reminder content changing per turn, dynamic "
                f"context tail (timestamps, counters), or session-meta inserted after a "
                f"stable prefix. Inspect transcript at the flagged turns for what changed."
            ),
            evidence={
                "invalidation_turn_count": count,
                "total_dropped_tokens": total,
                "mean_drop_per_invalidation": mean,
                "invalidation_turn_indexes": [ti for ti, _ in invalidations][:20],
            },
            evidence_kind="confirmed",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=[finding],
        )
