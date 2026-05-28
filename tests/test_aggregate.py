import tempfile
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


def test_expand_paths_single_file():
    from tlp.aggregate.run import expand_paths
    fix = Path("tests/fixtures/synthetic/minimal_trace.jsonl")
    out = expand_paths([fix])
    assert out == [fix]


def test_expand_paths_directory_recursive():
    from tlp.aggregate.run import expand_paths
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    out = expand_paths([fix_dir])
    assert len(out) == 2
    assert all(p.suffix == ".jsonl" for p in out)


def test_expand_paths_missing_raises():
    from tlp.aggregate.run import expand_paths
    import pytest as _pytest
    with _pytest.raises(FileNotFoundError):
        expand_paths([Path("/nonexistent/dir/")])


def test_aggregate_empty_input_returns_empty_report():
    from tlp.aggregate.run import aggregate
    with tempfile.TemporaryDirectory() as td:
        rep = aggregate([Path(td)])
    assert rep.session_count == 0
    assert rep.sessions == ()
    assert rep.median_leak_ratio == 0.0


def test_aggregate_two_sessions_flags_outlier():
    from tlp.aggregate.run import aggregate
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    assert rep.session_count == 2
    # The outlier fixture should be flagged (its leak_ratio is >> median × 2)
    outliers = [s for s in rep.sessions if s.is_outlier]
    assert len(outliers) >= 1
    assert any("outlier" in s.session_id for s in outliers)


def test_aggregate_single_session_no_outlier():
    """Single-session aggregation can't have outliers — median equals self."""
    from tlp.aggregate.run import aggregate
    rep = aggregate([Path("tests/fixtures/synthetic/aggregate/session_normal.jsonl")])
    assert rep.session_count == 1
    assert rep.sessions[0].is_outlier is False
