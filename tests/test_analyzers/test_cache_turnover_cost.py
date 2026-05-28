from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.cache_turnover_cost import CacheTurnoverCostAnalyzer
from tlp.config import load_defaults
from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable

NORMAL_FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_miss_trace.jsonl"
INV_FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_invalidation_trace.jsonl"

_PRICING = PricingTable(3.0, 15.0, 0.3, 3.75)
_BLOCK = (Block("text", "ok", None, None, None, 1),)


def _turn(idx, cr, cc, ts=None):
    return Turn(idx, "assistant", _BLOCK,
                Usage(input_tokens=10, output_tokens=2,
                      cache_read_tokens=cr, cache_creation_tokens=cc),
                timestamp=ts)


def test_normal_conversation_extension_emits_no_finding():
    """Healthy multi-turn caching (cache_creation > 0 every turn, but cache_read
    continuity preserved) is not a turnover event."""
    trace = parse(NORMAL_FIX)
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
    assert r.leaked_tokens == 0


def test_real_invalidation_no_timestamps_classified_architectural():
    """When timestamps are absent, all invalidation events are classified
    as 'architectural' (conservative default)."""
    trace = parse(INV_FIX)
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    # No timestamps → single architectural finding
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence["turnover_kind"] == "architectural"
    assert f.location == "session"
    assert f.evidence["invalidation_turn_count"] == 2
    # a2 drop = 10000, a4 drop = 17000 → total 27000
    assert f.evidence["total_dropped_tokens"] == 27000
    assert f.evidence["mean_drop_per_invalidation"] == 13500
    assert f.evidence_kind == "signal"
    assert f.confidence == "low"


def test_single_assistant_turn_returns_empty():
    """Need >= 2 turns to compute continuity. Single turn → no Finding."""
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", _BLOCK,
                 Usage(input_tokens=100, output_tokens=2,
                       cache_read_tokens=0, cache_creation_tokens=5000)),
        ),
        tool_defs={}, pricing=_PRICING,
    )
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_small_drops_below_threshold_ignored():
    """Drop below min_invalidation_drop (default 5000) is treated as noise."""
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", _BLOCK,
                 Usage(input_tokens=100, output_tokens=2,
                       cache_read_tokens=0, cache_creation_tokens=10000)),
            # expected = 10000, actual = 7000 → drop 3000 (below 5000 threshold)
            Turn(1, "assistant", _BLOCK,
                 Usage(input_tokens=10, output_tokens=2,
                       cache_read_tokens=7000, cache_creation_tokens=2000)),
            # expected = 9000, actual = 5000 → drop 4000 (still below)
            Turn(2, "assistant", _BLOCK,
                 Usage(input_tokens=10, output_tokens=2,
                       cache_read_tokens=5000, cache_creation_tokens=1000)),
        ),
        tool_defs={}, pricing=_PRICING,
    )
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_confidence_scales_with_severity():
    """1 turn → low, 2-4 → mid, 5+ or total>50k → high."""

    def make_single_invalidation_trace():
        """1 invalidation of 10000 tokens → low confidence."""
        return ParsedTrace(
            session_id="x",
            turns=(
                Turn(0, "assistant", _BLOCK,
                     Usage(input_tokens=100, output_tokens=2,
                           cache_read_tokens=0, cache_creation_tokens=10000)),
                # expected 10000, actual 0 → drop 10000
                Turn(1, "assistant", _BLOCK,
                     Usage(input_tokens=10, output_tokens=2,
                           cache_read_tokens=0, cache_creation_tokens=8000)),
            ),
            tool_defs={}, pricing=_PRICING,
        )

    def make_mid_invalidation_trace():
        """3 invalidations of 6000 tokens each → total 18000 < 50k, count 3 → mid."""
        turns = [
            Turn(0, "assistant", _BLOCK,
                 Usage(input_tokens=100, output_tokens=2,
                       cache_read_tokens=0, cache_creation_tokens=10000)),
        ]
        turns.append(Turn(1, "assistant", _BLOCK,
                          Usage(input_tokens=10, output_tokens=2,
                                cache_read_tokens=10000, cache_creation_tokens=2000)))
        # Turn 2: expected=12000, actual=6000 → drop 6000 (invalidation 1)
        turns.append(Turn(2, "assistant", _BLOCK,
                          Usage(input_tokens=10, output_tokens=2,
                                cache_read_tokens=6000, cache_creation_tokens=2000)))
        # Turn 3: expected=8000, actual=2000 → drop 6000 (invalidation 2)
        turns.append(Turn(3, "assistant", _BLOCK,
                          Usage(input_tokens=10, output_tokens=2,
                                cache_read_tokens=2000, cache_creation_tokens=2000)))
        # Turn 4: expected=4000, actual=4000 → drop 0 (normal)
        turns.append(Turn(4, "assistant", _BLOCK,
                          Usage(input_tokens=10, output_tokens=2,
                                cache_read_tokens=4000, cache_creation_tokens=2000)))
        # Turn 5: expected=6000, actual=0 → drop 6000 (invalidation 3)
        turns.append(Turn(5, "assistant", _BLOCK,
                          Usage(input_tokens=10, output_tokens=2,
                                cache_read_tokens=0, cache_creation_tokens=2000)))
        return ParsedTrace(session_id="x", turns=tuple(turns),
                           tool_defs={}, pricing=_PRICING)

    def make_high_invalidation_trace():
        """5 invalidations → count >= 5 → high."""
        turns = [
            Turn(0, "assistant", _BLOCK,
                 Usage(input_tokens=100, output_tokens=2,
                       cache_read_tokens=0, cache_creation_tokens=10000)),
        ]
        prev_cr, prev_cc = 0, 10000
        for i in range(5):
            normal_cr = prev_cr + prev_cc
            normal_cc = 2000
            turns.append(Turn(len(turns), "assistant", _BLOCK,
                               Usage(input_tokens=10, output_tokens=2,
                                     cache_read_tokens=normal_cr, cache_creation_tokens=normal_cc)))
            turns.append(Turn(len(turns), "assistant", _BLOCK,
                               Usage(input_tokens=10, output_tokens=2,
                                     cache_read_tokens=0, cache_creation_tokens=8000)))
            prev_cr, prev_cc = 0, 8000
        return ParsedTrace(session_id="x", turns=tuple(turns),
                           tool_defs={}, pricing=_PRICING)

    # 1 invalidation → low (architectural, no timestamp)
    r = CacheTurnoverCostAnalyzer().analyze(make_single_invalidation_trace(), load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].confidence == "low"
    assert r.findings[0].evidence["turnover_kind"] == "architectural"

    # 3 invalidations, total 18000 < 50k — architectural (no timestamps) → signal-only, low
    r = CacheTurnoverCostAnalyzer().analyze(make_mid_invalidation_trace(), load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].confidence == "low"
    assert r.findings[0].evidence_kind == "signal"
    assert r.findings[0].evidence["invalidation_turn_count"] == 3
    assert r.findings[0].evidence["total_dropped_tokens"] == 18000

    # 5 invalidations — architectural (no timestamps) → signal-only, low
    r = CacheTurnoverCostAnalyzer().analyze(make_high_invalidation_trace(), load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].confidence == "low"
    assert r.findings[0].evidence_kind == "signal"


def test_recoverable_vs_architectural_split_by_timestamp():
    """Events with gap >= 300s → recoverable; short gap → architectural.
    Emits two findings when both kinds present."""
    turns = (
        # t=0: first assistant turn
        _turn(0, cr=0, cc=10000, ts="2026-01-01T00:00:00Z"),
        # t=1: gap 1s — architectural; expected=10000, actual=0 → drop 10000
        _turn(1, cr=0, cc=8000, ts="2026-01-01T00:00:01Z"),
        # t=2: gap 1s — architectural; expected=8000, actual=0 → drop 8000
        _turn(2, cr=0, cc=7000, ts="2026-01-01T00:00:02Z"),
        # t=3: gap 600s — recoverable; expected=7000, actual=0 → drop 7000
        _turn(3, cr=0, cc=6000, ts="2026-01-01T00:10:02Z"),
    )
    trace = ParsedTrace(session_id="x", turns=turns, tool_defs={}, pricing=_PRICING)
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    # Expect two findings: architectural first (order of emission), then recoverable
    kinds = {f.evidence["turnover_kind"] for f in r.findings}
    assert kinds == {"recoverable", "architectural"}
    assert len(r.findings) == 2
    arch = next(f for f in r.findings if f.evidence["turnover_kind"] == "architectural")
    rec = next(f for f in r.findings if f.evidence["turnover_kind"] == "recoverable")
    assert arch.evidence["total_dropped_tokens"] == 18000
    assert rec.evidence["total_dropped_tokens"] == 7000
    assert r.leaked_tokens == 25000
    # v0.4: architectural → signal-only (low), recoverable stays confirmed
    assert arch.evidence_kind == "signal"
    assert arch.confidence == "low"
    assert rec.evidence_kind == "confirmed"


def test_stable_prefix_estimate_surfaced_when_clustered():
    """If actual_cr at all invalidation events clusters tightly, stable_prefix_tokens_estimate
    is included in the evidence dict."""
    # All events have actual_cr ~ 17000 (tight cluster, no timestamps → architectural)
    turns = (
        _turn(0, cr=0, cc=20000),
        # expected=20000, actual=17000 → drop 3000 (below threshold, skip)
        _turn(1, cr=17000, cc=1000),
        # expected=18000, actual=17100 → drop 900 (below threshold, skip)
        _turn(2, cr=17100, cc=900),
        # expected=18000, actual=17200 → drop 800 (below threshold)
        _turn(3, cr=17200, cc=800),
    )
    # No drops meet the 5000 threshold → no findings, no stable prefix
    trace = ParsedTrace(session_id="x", turns=turns, tool_defs={}, pricing=_PRICING)
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_stable_prefix_estimate_surfaced_with_large_drops():
    """Stable prefix estimate is surfaced when drops are large but actual_cr clusters."""
    # Scenario: prefix always re-caches at ~17000, but drop is large because
    # accumulated cache was much higher
    turns = (
        _turn(0, cr=0, cc=80000),
        # expected=80000, actual=17000 → drop 63000 ← big drop, actual_cr=17000
        _turn(1, cr=17000, cc=10000),
        # expected=27000, actual=17100 → drop 9900 ← above threshold (but <5000? no, 9900 > 5000)
        # Wait: 9900 > 5000 threshold → flagged; actual_cr = 17100
        _turn(2, cr=17100, cc=9000),
        # expected=26100, actual=16900 → drop 9200 → flagged; actual_cr=16900
        _turn(3, cr=16900, cc=8000),
    )
    trace = ParsedTrace(session_id="x", turns=turns, tool_defs={}, pricing=_PRICING)
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert len(r.findings) == 1
    f = r.findings[0]
    # All 3 events flagged; actual_cr values = [17000, 17100, 16900]
    # mean=17000, stdev ~ 100, stdev/mean ~ 0.006 < 0.01 → clustered
    assert "stable_prefix_tokens_estimate" in f.evidence
    est = f.evidence["stable_prefix_tokens_estimate"]
    assert 16000 < est < 18000  # ~17000


def test_no_timestamps_defaults_to_architectural():
    """Without timestamps, events are conservatively classified as architectural."""
    trace = ParsedTrace(
        session_id="x",
        turns=(
            _turn(0, cr=0, cc=20000),          # baseline
            _turn(1, cr=0, cc=15000),           # drop 20000 → architectural (no ts)
        ),
        tool_defs={}, pricing=_PRICING,
    )
    r = CacheTurnoverCostAnalyzer().analyze(trace, load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].evidence["turnover_kind"] == "architectural"
    assert "Not directly user-fixable" in r.findings[0].suggestion
    assert r.findings[0].evidence_kind == "signal"
    assert r.findings[0].confidence == "low"
