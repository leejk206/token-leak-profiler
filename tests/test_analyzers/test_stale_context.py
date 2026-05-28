from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.stale_context import StaleContextAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "stale_trace.jsonl"


def test_initial_block_flagged_stale():
    trace = parse(FIX)
    cfg = load_defaults()
    report = StaleContextAnalyzer().analyze(trace, cfg)
    locations = [f.location for f in report.findings]
    # turn 0 (initial user) should be flagged stale by end of trace
    assert any("turn[0]" in loc for loc in locations)
    assert report.leaked_tokens > 0


def test_no_stale_in_short_trace():
    # Trace shorter than stale_after_turns should have no findings
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    short = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "user", (Block("text", "hi", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = StaleContextAnalyzer().analyze(short, load_defaults())
    assert r.findings == []


def test_recently_referenced_not_stale():
    # build a 7-turn trace where turn 0 is referenced at turn 5
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    def t(i, role, text):
        u = Usage(10, 1, 0, 0) if role == "assistant" else None
        return Turn(i, role, (Block("text", text, None, None, None, len(text)//4 or 1),), u)
    trace = ParsedTrace(
        session_id="x",
        turns=(
            t(0, "user", "alpha bravo charlie delta echo foxtrot"),
            t(1, "assistant", "ok"),
            t(2, "user", "unrelated"),
            t(3, "assistant", "ok"),
            t(4, "user", "more unrelated"),
            t(5, "assistant", "alpha bravo charlie delta echo foxtrot again"),
            t(6, "user", "newer"),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = StaleContextAnalyzer().analyze(trace, load_defaults())
    # turn 0 was referenced at turn 5; (5 + 5) = 10 > 6, so not yet stale
    assert all("turn[0]" not in f.location for f in r.findings)
