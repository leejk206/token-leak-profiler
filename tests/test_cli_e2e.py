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
    assert len(data["reports"]) == 6


def test_analyze_table_default():
    r = _run("analyze", str(FIX))
    assert r.returncode == 0
    assert "tool_schema_bloat" in r.stdout
    assert "Token Leak Profile" in r.stdout


def test_missing_file_exit_1():
    r = _run("analyze", "/nonexistent/path.jsonl")
    assert r.returncode == 1


def test_filter_analyzers():
    r = _run("analyze", str(FIX), "--format", "json", "--analyzers", "tool_schema_bloat")
    data = json.loads(r.stdout)
    assert len(data["reports"]) == 1
    assert data["reports"][0]["analyzer"] == "tool_schema_bloat"
