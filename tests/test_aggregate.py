from pathlib import Path
from tlp.aggregate.types import SessionRow, AggregateReport


def test_session_row_construction():
    row = SessionRow(
        session_id="s1",
        label="my session",
        path=Path("/tmp/s1.jsonl"),
        turn_count=10,
        total_cost_usd=1.0,
        effective_leak_cost_usd=0.1,
        leak_ratio=0.1,
        dominant_lever="stale_context",
        is_outlier=False,
    )
    assert row.session_id == "s1"
    assert row.is_outlier is False


def test_aggregate_report_construction():
    rep = AggregateReport(
        sessions=(),
        total_cost_usd=0.0,
        total_effective_leak_usd=0.0,
        median_leak_ratio=0.0,
        outlier_threshold=0.0,
        session_count=0,
    )
    assert rep.session_count == 0
