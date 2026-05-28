from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.reasoning_overrun import ReasoningOverrunAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "reasoning_trace.jsonl"


def test_thinking_dwarfs_output_flagged():
    trace = parse(FIX)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert any("turn[0]" in f.location for f in r.findings)


def test_no_thinking_no_findings():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (Block("text", "hello", None, None, None, 2),),
                 Usage(10, 2, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
