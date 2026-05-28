import json as json_module
import tempfile
from io import StringIO
from pathlib import Path

from rich.console import Console

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


def test_render_table_shows_session_rows_and_summary():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_table
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    render_table(rep, console=console)
    output = buf.getvalue()
    assert "Aggregate" in output
    assert "Total:" in output
    assert "Median session leak" in output
    # At least one session label
    assert "agg-normal" in output or "<unknown>" in output


def test_render_table_marks_outlier_visibly():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_table
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    render_table(rep, console=console)
    output = buf.getvalue()
    assert "OUTLIER" in output


def test_render_json_returns_valid_payload():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_json
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    out = render_json(rep)
    data = json_module.loads(out)
    assert data["session_count"] == 2
    assert "sessions" in data
    assert "total_cost_usd" in data
    assert "median_leak_ratio" in data
    assert "outlier_threshold" in data
    # Each session has expected keys
    assert "leak_ratio" in data["sessions"][0]
    assert "is_outlier" in data["sessions"][0]
    assert "dominant_lever" in data["sessions"][0]


def test_expand_paths_excludes_subagent_dirs(tmp_path):
    from tlp.aggregate.run import expand_paths
    # Parent session
    parent = tmp_path / "parent.jsonl"
    parent.write_text("{}\n")
    # Subagent sidechain
    sub_dir = tmp_path / "abc" / "subagents"
    sub_dir.mkdir(parents=True)
    sub = sub_dir / "agent-1.jsonl"
    sub.write_text("{}\n")
    result = expand_paths([tmp_path])
    assert parent in result
    assert sub not in result


def test_expand_paths_includes_subagents_when_flag_set(tmp_path):
    from tlp.aggregate.run import expand_paths
    parent = tmp_path / "parent.jsonl"
    parent.write_text("{}\n")
    sub_dir = tmp_path / "abc" / "subagents"
    sub_dir.mkdir(parents=True)
    sub = sub_dir / "agent-1.jsonl"
    sub.write_text("{}\n")
    # Default: excluded
    out_default = expand_paths([tmp_path])
    assert sub not in out_default
    # With flag: included
    out_inc = expand_paths([tmp_path], include_subagents=True)
    assert sub in out_inc


def test_aggregate_zero_median_still_flags_high_ratio_via_floor(tmp_path):
    """When most sessions have leak_ratio=0, an above-floor session still flags."""
    from tlp.aggregate.run import aggregate
    # 3 zero-ratio sessions
    for i in range(3):
        p = tmp_path / f"zero_{i}.jsonl"
        p.write_text(
            '{"type":"user","sessionId":"z' + str(i) + '","uuid":"u","message":{"role":"user","content":"hi"}}\n'
            '{"type":"assistant","sessionId":"z' + str(i) + '","uuid":"a","message":{"role":"assistant","id":"mz' + str(i) + '","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":100,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
        )
    # 1 outlier with high leak ratio (reuse existing fixture by copy)
    import shutil
    shutil.copy(
        "tests/fixtures/synthetic/aggregate/session_outlier.jsonl",
        tmp_path / "outlier.jsonl",
    )
    rep = aggregate([tmp_path])
    assert rep.session_count == 4
    outliers = [s for s in rep.sessions if s.is_outlier]
    assert len(outliers) >= 1, (
        f"Expected at least one outlier via absolute floor; got median={rep.median_leak_ratio}, "
        f"threshold={rep.outlier_threshold}, sessions={[(s.label, s.leak_ratio, s.is_outlier) for s in rep.sessions]}"
    )
