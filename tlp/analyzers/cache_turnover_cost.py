from __future__ import annotations
from datetime import datetime
from tlp.analyzers.base import BaseAnalyzer
from tlp.analyzers._helpers import estimate_stable_prefix
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class CacheTurnoverCostAnalyzer(BaseAnalyzer):
    """Detect and categorize prompt-cache turnover events.

    Healthy multi-turn conversations always have cache_creation > 0 — the new
    tail content (assistant output + tool_result) is cached for future reuse.
    A turnover event is when an EXISTING cached prefix is invalidated and has
    to be re-cached. We detect this by comparing observed `cache_read` against
    the value expected from continuity: `prev.cache_read + prev.cache_creation`.

    When `actual < expected` by a non-trivial margin, the gap represents tokens
    we paid the expensive `cache_creation` rate to re-cache.

    Crucially, turnover events are NOT always user-fixable. Claude Code
    re-caches all conversation history on every new user turn by design. This
    analyzer categorizes events by recoverability:

    - **recoverable**: preceded by a long idle gap (>= min_recoverable_gap_seconds,
      default 300 s) — likely a TTL expiry or idle session the user could avoid.
    - **architectural**: short gap between turns — Claude Code default
      conversation-extension behavior; NOT directly user-fixable.

    Without timestamp data, defaults conservatively to "architectural".

    If the `actual_cr` values at invalidation events are tightly clustered
    (std-dev < 1% of mean), a `stable_prefix_tokens_estimate` is surfaced — this
    is the stable system-prompt + tool-definition prefix that is re-cached every
    turn.
    """

    name = "cache_turnover_cost"
    lever = LeverCategory.CACHE_TURNOVER_COST
    usage_bucket = "cache_creation"
    prescription = "Reduce idle time below 5 min (recoverable findings)"
    measurement_basis = "measured"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("cache_turnover_cost", {})
        min_drop = int(c.get("min_invalidation_drop", 5000))
        min_gap_s = int(c.get("min_recoverable_gap_seconds", 300))

        # Collect assistant turns with usage in document order
        # (turn_index, cache_read, cache_creation, timestamp_str | None)
        usages: list[tuple[int, int, int, str | None]] = []
        for turn in trace.turns:
            if turn.role != "assistant" or turn.usage is None:
                continue
            usages.append((
                turn.index,
                turn.usage.cache_read_tokens,
                turn.usage.cache_creation_tokens,
                getattr(turn, "timestamp", None),
            ))

        if len(usages) < 2:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        # Detect invalidation events and classify by recoverability
        recoverable_events: list[tuple[int, int, int]] = []  # (turn_index, drop, actual_cr)
        architectural_events: list[tuple[int, int, int]] = []  # same

        for i in range(1, len(usages)):
            ti, cr, _, ts = usages[i]
            prev_ti, prev_cr, prev_cc, prev_ts = usages[i - 1]
            expected_cr = prev_cr + prev_cc
            drop = expected_cr - cr
            if drop < min_drop:
                continue

            # Determine recoverability from timestamps
            kind = _classify_gap(prev_ts, ts, min_gap_s)
            if kind == "recoverable":
                recoverable_events.append((ti, drop, cr))
            else:
                architectural_events.append((ti, drop, cr))

        if not recoverable_events and not architectural_events:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        # Compute stable prefix estimate from all invalidation events' actual_cr
        all_actual_cr = [cr for _, _, cr in recoverable_events + architectural_events]
        stable_prefix_est = estimate_stable_prefix(all_actual_cr)

        findings: list[Finding] = []

        # Build recoverable finding
        if recoverable_events:
            total_r = sum(drop for _, drop, _ in recoverable_events)
            count_r = len(recoverable_events)
            mean_r = total_r // count_r
            confidence_r = _confidence(count_r, total_r)
            evidence_r: dict = {
                "turnover_kind": "recoverable",
                "invalidation_turn_count": count_r,
                "total_dropped_tokens": total_r,
                "mean_drop_per_invalidation": mean_r,
                "invalidation_turn_indexes": [ti for ti, _, _ in recoverable_events][:20],
            }
            if stable_prefix_est is not None and not architectural_events:
                # Only attach stable prefix to first finding when there's one kind
                evidence_r["stable_prefix_tokens_estimate"] = stable_prefix_est
            suggestion_r = (
                f"{count_r} cache turnover event(s) preceded by a long idle gap "
                f"(>= {min_gap_s}s, likely TTL expiry). "
                f"Avg {mean_r} tokens re-cached per event. "
                f"These events may be recoverable by reducing idle session time."
            )
            if stable_prefix_est is not None and not architectural_events:
                suggestion_r += (
                    f" Stable cache prefix detected: ~{stable_prefix_est} tokens "
                    f"(system prompt + tool definitions). Each new user turn re-caches "
                    f"all conversation history above this prefix."
                )
            findings.append(Finding(
                location="session",
                leaked_tokens=total_r,
                confidence=confidence_r,
                suggestion=suggestion_r,
                evidence=evidence_r,
                evidence_kind="confirmed",
            ))

        # Build architectural finding
        if architectural_events:
            total_a = sum(drop for _, drop, _ in architectural_events)
            count_a = len(architectural_events)
            mean_a = total_a // count_a
            evidence_a: dict = {
                "turnover_kind": "architectural",
                "invalidation_turn_count": count_a,
                "total_dropped_tokens": total_a,
                "mean_drop_per_invalidation": mean_a,
                "invalidation_turn_indexes": [ti for ti, _, _ in architectural_events][:20],
            }
            if stable_prefix_est is not None:
                evidence_a["stable_prefix_tokens_estimate"] = stable_prefix_est
            suggestion_a = (
                f"{count_a} cache turnover event(s) are Claude Code default behavior "
                f"(new user turn → re-cache history). Not directly user-fixable — "
                f"signal-only measurement, included for awareness. "
                f"Avg {mean_a} tokens re-cached per event."
            )
            if stable_prefix_est is not None:
                suggestion_a += (
                    f" Stable cache prefix detected: ~{stable_prefix_est} tokens "
                    f"(system prompt + tool definitions). Each new user turn re-caches "
                    f"all conversation history above this prefix."
                )
            findings.append(Finding(
                location="session",
                leaked_tokens=total_a,
                confidence="low",
                suggestion=suggestion_a,
                evidence=evidence_a,
                evidence_kind="signal",
            ))

        total_all = sum(f.leaked_tokens for f in findings)
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total_all, leaked_cost_usd=0.0, findings=findings,
        )


def _confidence(count: int, total: int) -> str:
    if count >= 5 or total > 50_000:
        return "high"
    elif count >= 2:
        return "mid"
    else:
        return "low"


def _classify_gap(prev_ts: str | None, curr_ts: str | None, min_gap_s: int) -> str:
    """Return 'recoverable' if the gap between timestamps >= min_gap_s, else 'architectural'.

    If timestamps are missing or unparseable, defaults conservatively to 'architectural'.
    """
    if prev_ts is None or curr_ts is None:
        return "architectural"
    try:
        t_prev = _parse_ts(prev_ts)
        t_curr = _parse_ts(curr_ts)
        gap_s = (t_curr - t_prev).total_seconds()
        return "recoverable" if gap_s >= min_gap_s else "architectural"
    except Exception:
        return "architectural"


def _parse_ts(ts: str) -> datetime:
    """Parse ISO-8601 timestamp, handling 'Z' suffix and milliseconds."""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)
