import json
import pytest
from tlp.reporter.json_renderer import render_json
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
