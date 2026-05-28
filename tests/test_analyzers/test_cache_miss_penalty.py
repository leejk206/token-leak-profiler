"""Legacy test file kept for historical reference. See test_cache_turnover_cost.py for current tests.

These tests are preserved but now exercise CacheTurnoverCostAnalyzer (renamed from
CacheMissPenaltyAnalyzer in v0.3.3). All findings are now classified by recoverability;
without timestamps the behavior defaults to architectural, matching these test assertions.
"""
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.cache_turnover_cost import CacheTurnoverCostAnalyzer as CacheMissPenaltyAnalyzer
from tlp.config import load_defaults

NORMAL_FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_miss_trace.jsonl"
INV_FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_invalidation_trace.jsonl"


def test_normal_conversation_extension_emits_no_finding():
    """Healthy multi-turn caching (cache_creation > 0 every turn, but cache_read
    continuity preserved) is not a leak."""
    trace = parse(NORMAL_FIX)
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
    assert r.leaked_tokens == 0


def test_real_invalidation_pattern_flagged():
    """When cache_read drops below expected (prev.cr + prev.cc), that's real
    prefix invalidation worth flagging."""
    trace = parse(INV_FIX)
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.location == "session"
    assert f.evidence["invalidation_turn_count"] == 2
    # a2 drop = 10000, a4 drop = 17000 → total 27000
    assert f.evidence["total_dropped_tokens"] == 27000
    assert f.evidence["mean_drop_per_invalidation"] == 13500
    assert f.evidence_kind == "confirmed"


def test_single_assistant_turn_returns_empty():
    """Need ≥2 turns to compute continuity. Single turn → no Finding."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_small_drops_below_threshold_ignored():
    """Drop below min_invalidation_drop (default 5000) is treated as noise."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=10000)),
            # expected = 10000, actual = 7000 → drop 3000 (below 5000 threshold)
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=7000, cache_creation_tokens=2000)),
            # expected = 9000, actual = 5000 → drop 4000 (still below)
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=5000, cache_creation_tokens=1000)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_confidence_scales_with_severity():
    """1 turn → low, 2-4 → mid, 5+ or total>50k → high."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable

    def make_single_invalidation_trace():
        """1 invalidation of 10000 tokens → low confidence."""
        return ParsedTrace(
            session_id="x",
            turns=(
                Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                     Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=10000)),
                # expected 10000, actual 0 → drop 10000
                Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                     Usage(input_tokens=10, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=8000)),
            ),
            tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
        )

    def make_mid_invalidation_trace():
        """3 invalidations of 6000 tokens each → total 18000 < 50k, count 3 → mid."""
        turns = [
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=10000)),
        ]
        # Build steady state then invalidate 3 times
        # Turn 1: cr=10000, cc=2000  → expected from t0: 10000 ✓ (no drop)
        turns.append(Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                          Usage(input_tokens=10, output_tokens=2, cache_read_tokens=10000, cache_creation_tokens=2000)))
        # Turn 2: expected=12000, actual=6000 → drop 6000 (invalidation 1)
        turns.append(Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                          Usage(input_tokens=10, output_tokens=2, cache_read_tokens=6000, cache_creation_tokens=2000)))
        # Turn 3: expected=8000, actual=2000 → drop 6000 (invalidation 2)
        turns.append(Turn(3, "assistant", (Block("text", "ok", None, None, None, 1),),
                          Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=2000)))
        # Turn 4: expected=4000, actual=4000 → drop 0 (normal)
        turns.append(Turn(4, "assistant", (Block("text", "ok", None, None, None, 1),),
                          Usage(input_tokens=10, output_tokens=2, cache_read_tokens=4000, cache_creation_tokens=2000)))
        # Turn 5: expected=6000, actual=0 → drop 6000 (invalidation 3)
        turns.append(Turn(5, "assistant", (Block("text", "ok", None, None, None, 1),),
                          Usage(input_tokens=10, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=2000)))
        return ParsedTrace(session_id="x", turns=tuple(turns),
                           tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75))

    def make_high_invalidation_trace():
        """5 invalidations → count ≥ 5 → high."""
        turns = [
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=10000)),
        ]
        # 5 pairs: each pair has a normal turn then an invalidation
        prev_cr, prev_cc = 0, 10000
        for i in range(5):
            # normal turn: cr = prev_cr + prev_cc
            normal_cr = prev_cr + prev_cc
            normal_cc = 2000
            turns.append(Turn(len(turns), "assistant", (Block("text", "ok", None, None, None, 1),),
                               Usage(input_tokens=10, output_tokens=2,
                                     cache_read_tokens=normal_cr, cache_creation_tokens=normal_cc)))
            # invalidation turn: expected = normal_cr + normal_cc, actual = 0
            turns.append(Turn(len(turns), "assistant", (Block("text", "ok", None, None, None, 1),),
                               Usage(input_tokens=10, output_tokens=2,
                                     cache_read_tokens=0, cache_creation_tokens=8000)))
            prev_cr, prev_cc = 0, 8000
        return ParsedTrace(session_id="x", turns=tuple(turns),
                           tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75))

    # 1 invalidation → low
    r = CacheMissPenaltyAnalyzer().analyze(make_single_invalidation_trace(), load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].confidence == "low"

    # 3 invalidations, total 18000 < 50k → mid
    r = CacheMissPenaltyAnalyzer().analyze(make_mid_invalidation_trace(), load_defaults())
    assert r.findings[0].confidence == "mid"
    assert r.findings[0].evidence["invalidation_turn_count"] == 3
    assert r.findings[0].evidence["total_dropped_tokens"] == 18000

    # 5 invalidations → high
    r = CacheMissPenaltyAnalyzer().analyze(make_high_invalidation_trace(), load_defaults())
    assert r.findings[0].confidence == "high"
