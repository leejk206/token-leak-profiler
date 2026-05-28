from __future__ import annotations
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_table(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    findings_per_lever: int = 5,
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
) -> None:
    raise NotImplementedError("see Task 14")
