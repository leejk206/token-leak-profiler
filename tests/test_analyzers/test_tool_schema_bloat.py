from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.tool_schema_bloat import ToolSchemaBloatAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "bloat_trace.jsonl"


def test_flags_unused_tool_defs():
    trace = parse(FIX)
    r = ToolSchemaBloatAnalyzer().analyze(trace, load_defaults())
    flagged = {f.evidence.get("tool_name") for f in r.findings}
    assert "tool_dead_one" in flagged
    assert "tool_dead_two" in flagged
    assert "tool_used" not in flagged


def test_leaked_tokens_scale_with_assistant_turns():
    trace = parse(FIX)
    r = ToolSchemaBloatAnalyzer().analyze(trace, load_defaults())
    # 2 assistant turns × unused tool def tokens
    assert r.leaked_tokens > 0
    # The unused defs are non-trivial; ensure multiplier matches assistant_turns
    unused_tokens = sum(
        td.tokens for name, td in trace.tool_defs.items()
        if name in {"tool_dead_one", "tool_dead_two"}
    )
    assistant_turns = sum(1 for t in trace.turns if t.role == "assistant")
    assert r.leaked_tokens == unused_tokens * assistant_turns
