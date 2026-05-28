from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.roundtrip_inflation import RoundtripInflationAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "roundtrip_inflation_trace.jsonl"


def test_flags_consecutive_short_user_msgs():
    trace = parse(FIX)
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    # (run_length - 1) × estimated_assistant_response_tokens
    # = (5 - 1) × 500 = 2000
    assert f.leaked_tokens == 2000
    assert f.evidence_kind == "signal"
    assert f.confidence == "low"
    assert f.evidence["run_length"] == 5


def test_no_finding_below_min_run():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "user", (Block("text", "ok", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "r", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
            Turn(2, "user", (Block("text", "yes", None, None, None, 1),), None),
            Turn(3, "assistant", (Block("text", "r", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_long_user_msgs_break_run():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    long_text = "x" * 100
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "user", (Block("text", "ok", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(2, "user", (Block("text", "yes", None, None, None, 1),), None),
            Turn(3, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(4, "user", (Block("text", long_text, None, None, None, 25),), None),
            Turn(5, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(6, "user", (Block("text", "k", None, None, None, 1),), None),
            Turn(7, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
