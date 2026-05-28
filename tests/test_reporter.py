import json
import pytest
from io import StringIO

from rich.console import Console

from tlp.reporter.json_renderer import render_json
from tlp.reporter.table import render_table
from tlp.types import (
    ParsedTrace, Turn, Block, Usage, PricingTable,
    LeakReport, LeverCategory, Finding,
)


def _trace():
    return ParsedTrace(
        session_id="sess-x",
        turns=(
            Turn(0, "user", (Block("text", "hi", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(100, 50, 0, 0)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )


def test_json_includes_session_and_totals():
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {})],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"stale_context": "input"})
    data = json.loads(out)
    assert data["session_id"] == "sess-x"
    assert data["total_input_tokens"] == 100
    assert data["total_output_tokens"] == 50
    assert data["reports"][0]["analyzer"] == "stale_context"
    # 20 tok × $3 / Mtok
    assert data["reports"][0]["leaked_cost_usd"] == pytest.approx(20 * 3.0 / 1_000_000)
    assert data["total_cost_usd"] > 0


def test_json_handles_analyzer_error():
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=0, leaked_cost_usd=0.0,
            findings=[], error="boom",
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"reasoning_overrun": "output"})
    data = json.loads(out)
    assert data["reports"][0]["error"] == "boom"


def test_json_includes_effective_cost():
    """Effective cost should reflect the blended input rate when cache_read is heavy."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable, LeakReport, LeverCategory, Finding
    trace_with_cache = ParsedTrace(
        session_id="cached",
        turns=(
            Turn(0, "user", (Block("text", "hi", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 # 100 fresh input + 10,000 cache_read + 1,000 cache_creation
                 Usage(100, 50, 10_000, 1_000)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=1000, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 1000, "mid", "compress", {})],
        ),
    ]
    out = render_json(trace_with_cache, reports, bucket_map={"stale_context": "input"})
    data = json.loads(out)
    rpt = data["reports"][0]
    # Conservative: 1000 tok × $3/Mtok = $0.003
    assert rpt["leaked_cost_usd"] == pytest.approx(0.003)
    # Effective is lower since most "input" is actually cached
    assert rpt["effective_cost_usd"] < rpt["leaked_cost_usd"]
    assert data["blended_input_rate_per_mtok"] < 3.0


def test_table_includes_lever_rows_and_totals():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress this please", {})],
        ),
        LeakReport(
            analyzer="tool_schema_bloat", lever=LeverCategory.TOOL_SCHEMA_BLOAT,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("tool_def[unused]", 80, "high", "drop tool", {})],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input", "tool_schema_bloat": "input"},
        console=console,
    )
    output = buf.getvalue()
    assert "sess-x" in output
    assert "stale_context" in output
    assert "tool_schema_bloat" in output
    assert "compress this please" in output
    assert "drop tool" in output
