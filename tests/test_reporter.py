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
            analyzer="verbose_tool_results", lever=LeverCategory.VERBOSE_TOOL_RESULTS,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("turn[1]", 80, "high", "shorten result", {})],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input", "verbose_tool_results": "output"},
        console=console,
    )
    output = buf.getvalue()
    assert "sess-x" in output
    assert "stale_context" in output
    assert "verbose_tool_results" in output
    assert "compress this please" in output
    assert "shorten result" in output


def test_json_includes_confirmed_and_signal_totals():
    from tlp.types import LeakReport, LeverCategory, Finding
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {}, "confirmed")],
        ),
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("turn[5]", 80, "low", "review", {}, "signal")],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={
        "stale_context": "input", "reasoning_overrun": "output"
    })
    data = json.loads(out)
    assert "confirmed_leak_cost_usd" in data
    assert "signal_attention_cost_usd" in data
    assert "effective_leak_cost_usd" in data
    # Confirmed cost is 20 × $3/Mtok = $0.00006
    assert data["confirmed_leak_cost_usd"] == pytest.approx(20 * 3.0 / 1_000_000)
    # Signal cost is 80 × $15/Mtok = $0.0012
    assert data["signal_attention_cost_usd"] == pytest.approx(80 * 15.0 / 1_000_000)


def test_json_per_report_breakdown_fields_present():
    from tlp.types import LeakReport, LeverCategory, Finding
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=100, leaked_cost_usd=0.0,
            findings=[
                Finding("a", 40, "mid", "x", {}, "confirmed"),
                Finding("b", 60, "low", "x", {}, "signal"),
            ],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"reasoning_overrun": "output"})
    data = json.loads(out)
    rpt = data["reports"][0]
    assert rpt["confirmed_tokens"] == 40
    assert rpt["signal_tokens"] == 60
    assert rpt["findings"][0]["evidence_kind"] == "confirmed"
    assert rpt["findings"][1]["evidence_kind"] == "signal"


def test_json_no_longer_emits_total_effective_leak_cost_usd():
    """v1's total_effective_leak_cost_usd is renamed to effective_leak_cost_usd."""
    out = render_json(_trace(), [], bucket_map={})
    data = json.loads(out)
    assert "total_effective_leak_cost_usd" not in data
    assert "effective_leak_cost_usd" in data


def test_table_shows_two_separate_summary_lines():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {}, "confirmed")],
        ),
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("turn[5]", 80, "low", "review", {}, "signal")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input", "reasoning_overrun": "output"},
        console=console,
    )
    output = buf.getvalue()
    assert "Confirmed leak:" in output
    assert "Attention signals:" in output
    assert "Effective leak" in output
    # "Estimated total leak" header should be GONE
    assert "Estimated total leak" not in output


def test_table_findings_section_shows_kind_column():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=100, leaked_cost_usd=0.0,
            findings=[
                Finding("turn[1]", 50, "mid", "dup detected", {}, "confirmed"),
                Finding("turn[2]", 50, "low", "ratio high", {}, "signal"),
            ],
        ),
    ]
    render_table(
        _trace(), reports,
        bucket_map={"reasoning_overrun": "output"},
        console=console,
    )
    output = buf.getvalue()
    assert "kind" in output.lower()
    assert "CONF" in output
    assert "SIG" in output


def test_table_includes_v0_4_framing_line():
    """v0.4.0: table output explicitly distinguishes actionable from signal."""
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "low", "review", {}, "signal")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input"},
        console=console,
    )
    output = buf.getvalue()
    assert "actionable" in output.lower()
    assert "inspect before acting" in output.lower()


def test_table_shows_estimated_leak_line():
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="mcp_server_overhead", lever=LeverCategory.MCP_SERVER_OVERHEAD,
            leaked_tokens=1000, leaked_cost_usd=0.0,
            findings=[Finding("mcp_server[demo]", 1000, "high", "disable", {}, "estimated")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"mcp_server_overhead": "input"},
        console=console,
    )
    output = buf.getvalue()
    assert "Estimated leak:" in output
    assert "heuristic" in output.lower()


def test_table_pct_includes_cache_buckets_in_denominator():
    """Regression: cache_turnover_cost leak should not produce >100% column."""
    from tlp.types import (
        ParsedTrace, Turn, Block, Usage, PricingTable, LeakReport, LeverCategory, Finding,
    )
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=50, cache_read_tokens=200_000, cache_creation_tokens=50_000)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    reports = [
        LeakReport(
            analyzer="cache_turnover_cost", lever=LeverCategory.CACHE_TURNOVER_COST,
            leaked_tokens=40_000, leaked_cost_usd=0.0,
            findings=[Finding("session", 40_000, "mid", "x", {}, "confirmed")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"cache_turnover_cost": "cache_creation"},
        console=console,
    )
    output = buf.getvalue()
    # 40000 / (100 + 50 + 200000 + 50000) = 16.0% — well under 100%
    import re
    match = re.search(r"cache_turnover_cost[^\n]*?(\d+\.\d+)%", output)
    assert match, f"Could not find % in output: {output}"
    pct = float(match.group(1))
    assert pct < 100.0, f"Percentage {pct}% exceeds 100% — denominator missing cache buckets"
