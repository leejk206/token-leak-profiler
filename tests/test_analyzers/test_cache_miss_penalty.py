from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.cache_miss_penalty import CacheMissPenaltyAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_miss_trace.jsonl"


def test_flags_recurring_cache_creation_pattern():
    trace = parse(FIX)
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.location == "session"
    assert f.evidence_kind == "confirmed"
    assert f.evidence["affected_turn_count"] == 4
    assert f.evidence["mean_creation_tokens"] == 3250


def test_no_finding_when_cache_creation_only_in_turn_0():
    """Initial cache build alone shouldn't fire — that's normal."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=5000, cache_creation_tokens=0)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=5000, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_when_below_threshold_count():
    """Fewer than min_recreation_turns affected → empty."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=2000)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=4000, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_when_mean_below_threshold():
    """Enough turns affected but mean cache_creation below threshold → empty."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=500)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=400)),
            Turn(3, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=300)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
