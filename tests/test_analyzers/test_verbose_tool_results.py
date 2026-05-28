from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.verbose_tool_results import VerboseToolResultsAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "verbose_tool_trace.jsonl"


def test_flags_verbose_tool_result():
    trace = parse(FIX)
    r = VerboseToolResultsAnalyzer().analyze(trace, load_defaults())
    assert any(f.evidence.get("tool_use_id") == "toolu_1" for f in r.findings)
    assert r.leaked_tokens > 0
    # v0.4.0: signal-only
    assert all(f.evidence_kind == "signal" for f in r.findings)
    assert all(f.confidence == "low" for f in r.findings)


def test_no_findings_when_cited():
    # tool_result text fully echoed by next assistant turn → no leak
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    payload = "key fact alpha bravo charlie delta echo foxtrot"
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("tool_use", None, "t", {}, "tu1", 1),), Usage(10, 1, 0, 0)),
            Turn(1, "tool_result", (Block("tool_result", payload, None, None, "tu1", len(payload)//4),), None),
            Turn(2, "assistant",
                 (Block("text", "Summary: " + payload, None, None, None, len(payload)//4),),
                 Usage(20, 5, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = VerboseToolResultsAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
