from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.format_boilerplate import FormatBoilerplateAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "boilerplate_trace.jsonl"


def test_detects_repeated_prefix():
    trace = parse(FIX)
    r = FormatBoilerplateAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert any("알겠습니다" in f.evidence.get("pattern", "") for f in r.findings)


def test_no_findings_without_repetition():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=tuple(
            Turn(i, "assistant",
                 (Block("text", f"completely unique reply number {i} with distinct prefix and suffix words", None, None, None, 20),),
                 Usage(10, 10, 0, 0))
            for i in range(4)
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = FormatBoilerplateAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
