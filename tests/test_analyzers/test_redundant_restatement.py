from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.redundant_restatement import RedundantRestatementAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "redundant_trace.jsonl"


def test_detects_repeated_user_message():
    trace = parse(FIX)
    r = RedundantRestatementAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    # The later occurrence (turn 2) should be flagged
    assert any("turn[2]" in f.location for f in r.findings)


def test_no_findings_when_all_unique():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    def t(i, txt):
        return Turn(i, "user" if i % 2 == 0 else "assistant",
                    (Block("text", txt, None, None, None, len(txt)//4 or 1),),
                    Usage(10, 1, 0, 0) if i % 2 else None)
    trace = ParsedTrace(
        session_id="x",
        turns=tuple(t(i, f"unique content number {i} totally distinct phrasing") for i in range(6)),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RedundantRestatementAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
