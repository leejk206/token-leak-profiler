import json
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "synthetic" / "bloat_trace.jsonl"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tlp.cli", *args],
        capture_output=True, text=True, check=False,
    )


def test_analyze_json_output():
    r = _run("analyze", str(FIX), "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["session_id"] == "s-bloat"
    assert len(data["reports"]) == 10


def test_analyze_table_default():
    r = _run("analyze", str(FIX))
    assert r.returncode == 0
    assert "stale_context" in r.stdout
    assert "Token Leak Profile" in r.stdout


def test_missing_file_exit_1():
    r = _run("analyze", "/nonexistent/path.jsonl")
    assert r.returncode == 1


def test_filter_analyzers():
    r = _run("analyze", str(FIX), "--format", "json", "--analyzers", "stale_context")
    data = json.loads(r.stdout)
    assert len(data["reports"]) == 1
    assert data["reports"][0]["analyzer"] == "stale_context"


def test_e2e_golden_bloat(tmp_path: Path):
    out = tmp_path / "out.json"
    r = _run("analyze", str(FIX), "--format", "json", "--output", str(out))
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    # Stable shape assertions (avoid full snapshot since floats and tokenizer
    # approximations may drift; lock structural invariants instead).
    assert data["session_id"] == "s-bloat"
    assert data["turn_count"] == 4
    analyzer_names = {r["analyzer"] for r in data["reports"]}
    assert analyzer_names == {
        "stale_context", "redundant_restatement",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_turnover_cost", "subagent_context_overdump",
        "system_prompt_audit", "roundtrip_inflation",
        "tool_result_repetition",
    }
    stale = next(r for r in data["reports"] if r["analyzer"] == "stale_context")
    assert isinstance(stale["leaked_tokens"], int)
    assert all("leaked_cost_usd" in r for r in data["reports"])
    assert all("usage_bucket" in r for r in data["reports"])


def test_strict_aborts_on_unknown_event(tmp_path: Path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type":"unknown-kind","message":{}}\n')
    r = _run("analyze", str(bad), "--strict")
    assert r.returncode != 0


def test_min_confidence_high_filters_and_zeros_tokens(tmp_path: Path):
    out = tmp_path / "out.json"
    r = _run("analyze", str(FIX), "--format", "json",
             "--output", str(out), "--min-confidence", "high")
    assert r.returncode == 0
    data = json.loads(out.read_text())
    for report in data["reports"]:
        # With high-only filter, mid-confidence findings drop and the token total
        # must match the sum of remaining findings (no orphan tokens).
        finding_sum = sum(f["leaked_tokens"] for f in report["findings"])
        assert report["leaked_tokens"] == finding_sum


def test_schema_dump_text_output():
    r = _run("schema-dump", str(FIX))
    assert r.returncode == 0, r.stderr
    assert "Session" in r.stdout
    assert "event types:" in r.stdout
    assert "usage totals:" in r.stdout


def test_schema_dump_json_output():
    r = _run("schema-dump", str(FIX), "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "session_id" in data
    assert "event_types" in data
    assert "assistant_block_types" in data


def test_schema_dump_missing_file_exit_1():
    r = _run("schema-dump", "/nonexistent/path.jsonl")
    assert r.returncode == 1


def test_no_args_shows_help():
    r = _run()
    # typer no-args returns 0 and prints help including both subcommands
    assert "analyze" in r.stdout or "analyze" in r.stderr
    assert "schema-dump" in r.stdout or "schema-dump" in r.stderr


def test_aggregate_directory_table():
    fix_dir = "tests/fixtures/synthetic/aggregate"
    r = _run("aggregate", fix_dir)
    assert r.returncode == 0, r.stderr
    assert "Aggregate" in r.stdout
    assert "Total:" in r.stdout


def test_aggregate_json_output():
    fix_dir = "tests/fixtures/synthetic/aggregate"
    r = _run("aggregate", fix_dir, "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["session_count"] == 2
    assert "outlier_threshold" in data


def test_aggregate_two_files_explicit():
    r = _run(
        "aggregate",
        "tests/fixtures/synthetic/aggregate/session_normal.jsonl",
        "tests/fixtures/synthetic/aggregate/session_outlier.jsonl",
        "--format", "json",
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["session_count"] == 2


def test_aggregate_missing_path_exit_1():
    r = _run("aggregate", "/nonexistent/dir/")
    assert r.returncode == 1


def test_aggregate_empty_dir_exit_0_no_sessions(tmp_path):
    r = _run("aggregate", str(tmp_path))
    assert r.returncode == 0
    assert "no sessions matched" in r.stdout.lower() or "no sessions matched" in r.stderr.lower()
