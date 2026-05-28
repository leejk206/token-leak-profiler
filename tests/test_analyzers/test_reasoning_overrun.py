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
    # Confidence "mid" because the token count itself is measured (from usage.output_tokens);
    # only the content is hidden.
    assert r.findings[0].confidence == "mid"
