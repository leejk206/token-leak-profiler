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


def test_redacted_thinking_estimated_from_usage_delta():
    """Real Claude Code transcripts have thinking blocks with empty text but
    signature-encrypted content. The tokens are still in usage.output_tokens —
    back them out via output - text - tool_use."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    from tlp.analyzers.reasoning_overrun import ReasoningOverrunAnalyzer
    from tlp.config import load_defaults

    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (
                # Redacted thinking block: kind=thinking, text="" → tokens=0
                Block("thinking", "", None, None, None, 0),
                Block("text", "Z.", None, None, None, 1),
            ), Usage(input_tokens=10, output_tokens=500, cache_read_tokens=0, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert r.findings[0].evidence["thinking_redacted"] is True
    # Ratio-only findings (no duplicate-sentence evidence) are "low" confidence —
    # high thinking/output ratio is a signal to investigate, not proven waste.
    assert r.findings[0].confidence == "low"


def test_visible_thinking_duplicate_sentence_is_confirmed():
    """When thinking content is visible AND duplicate-sentence detection fires,
    finding is confirmed (real measurement of waste)."""
    fix = Path(__file__).parent.parent / "fixtures" / "synthetic" / "visible_thinking_trace.jsonl"
    trace = parse(fix)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    # At least one finding from the duplicate-sentence path
    confirmed_findings = [f for f in r.findings if f.evidence_kind == "confirmed"]
    assert len(confirmed_findings) >= 1
    assert confirmed_findings[0].confidence == "mid"


def test_redacted_thinking_is_signal_not_confirmed():
    """Confirms evidence_kind is signal (not just confidence='low')."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (
                Block("thinking", "", None, None, None, 0),
                Block("text", "Z.", None, None, None, 1),
            ), Usage(input_tokens=10, output_tokens=500, cache_read_tokens=0, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.findings[0].evidence_kind == "signal"
    assert r.findings[0].confidence == "low"


def test_visible_thinking_emits_both_dup_and_ratio_findings():
    """When both duplicate-sentence detection AND overrun fire, we emit two
    distinct Findings (one confirmed, one signal) instead of lumping them."""
    fix = Path(__file__).parent.parent / "fixtures" / "synthetic" / "visible_thinking_split.jsonl"
    trace = parse(fix)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    confirmed = [f for f in r.findings if f.evidence_kind == "confirmed"]
    signal = [f for f in r.findings if f.evidence_kind == "signal"]
    assert len(confirmed) >= 1, f"no confirmed findings; got {r.findings}"
    assert len(signal) >= 1, f"no signal findings; got {r.findings}"
    assert any(".dup" in f.location for f in confirmed)
    assert any(".ratio" in f.location for f in signal)


def test_redacted_thinking_emits_only_ratio_finding():
    """Redacted thinking has no visible content → no duplicate detection.
    Only the ratio path fires → exactly one signal finding."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (
                Block("thinking", "", None, None, None, 0),
                Block("text", "Z.", None, None, None, 1),
            ), Usage(input_tokens=10, output_tokens=500, cache_read_tokens=0, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert len(r.findings) == 1
    assert r.findings[0].evidence_kind == "signal"
    assert ".ratio" in r.findings[0].location
