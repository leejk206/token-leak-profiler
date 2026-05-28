from pathlib import Path
from tlp.parser import parse
from tlp.types import ParsedTrace

FIX = Path(__file__).parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"


def test_parse_returns_parsed_trace():
    t = parse(FIX)
    assert isinstance(t, ParsedTrace)
    assert t.session_id == "sess-1"


def test_parse_turn_count_and_roles():
    t = parse(FIX)
    assert len(t.turns) == 3
    assert [tr.role for tr in t.turns] == ["user", "assistant", "tool_result"]


def test_parse_assistant_usage_populated():
    t = parse(FIX)
    a = t.turns[1]
    assert a.usage is not None
    assert a.usage.input_tokens == 120
    assert a.usage.output_tokens == 6


def test_parse_user_text_to_text_block():
    t = parse(FIX)
    u0 = t.turns[0]
    assert len(u0.blocks) == 1
    assert u0.blocks[0].kind == "text"
    assert u0.blocks[0].text == "Hello there, can you help with X?"
    assert u0.blocks[0].tokens > 0


def test_parse_tool_result_block():
    t = parse(FIX)
    tr = t.turns[2]
    assert tr.role == "tool_result"
    assert tr.blocks[0].kind == "tool_result"
    assert tr.blocks[0].tool_use_id == "toolu_1"
    assert tr.blocks[0].text == "42"


def test_parse_groups_streamed_assistant_events_by_message_id():
    """Claude Code splits one assistant response across multiple JSONL events
    (one per content block) and each event repeats the same usage. The parser
    must merge consecutive events sharing message.id into a single Turn so
    usage isn't double-counted and thinking blocks live with their tool_use."""
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "streaming_split_trace.jsonl"
    t = parse(fix)
    # 5 raw events → 4 turns: user, assistant(merged thinking+tool_use), tool_result, assistant
    assert len(t.turns) == 4
    assert [tr.role for tr in t.turns] == ["user", "assistant", "tool_result", "assistant"]

    merged = t.turns[1]
    assert [b.kind for b in merged.blocks] == ["thinking", "tool_use"]
    # Usage taken once, NOT summed across the two split events
    assert merged.usage is not None
    assert merged.usage.output_tokens == 268

    # Second logical message stays separate (different id)
    second = t.turns[3]
    assert [b.kind for b in second.blocks] == ["text"]
    assert second.usage.output_tokens == 3


def test_parse_total_usage_not_double_counted():
    """The streaming-split fixture has two assistant messages: one of 268 output
    tokens (split across 2 events) and one of 3. Total billed = 271, not 536."""
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "streaming_split_trace.jsonl"
    t = parse(fix)
    total_output = sum(tn.usage.output_tokens for tn in t.turns if tn.usage)
    assert total_output == 271


def test_parse_dedupes_non_consecutive_same_message_id():
    """A message.id that recurs after user/tool_result events (subagent tool
    loop pattern) must have its usage counted exactly once, not per occurrence."""
    import tempfile
    fixture = """\
{"type":"user","sessionId":"s-loop","uuid":"u1","message":{"role":"user","content":"start"}}
{"type":"assistant","sessionId":"s-loop","uuid":"a1","message":{"role":"assistant","id":"msg_LOOP","content":[{"type":"tool_use","id":"tu_1","name":"read","input":{}}],"usage":{"input_tokens":100,"output_tokens":200,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-loop","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"r1"}]}}
{"type":"assistant","sessionId":"s-loop","uuid":"a2","message":{"role":"assistant","id":"msg_LOOP","content":[{"type":"tool_use","id":"tu_2","name":"read","input":{}}],"usage":{"input_tokens":100,"output_tokens":200,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-loop","uuid":"u3","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_2","content":"r2"}]}}
{"type":"assistant","sessionId":"s-loop","uuid":"a3","message":{"role":"assistant","id":"msg_LOOP","content":[{"type":"text","text":"done"}],"usage":{"input_tokens":100,"output_tokens":200,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(fixture)
        path = Path(f.name)
    try:
        t = parse(path)
        # Total output: 200 (counted ONCE), not 600 (3 occurrences × 200)
        total_output = sum(tn.usage.output_tokens for tn in t.turns if tn.usage)
        assert total_output == 200, f"Expected 200 (single message), got {total_output}"
    finally:
        path.unlink()


def test_parse_extracts_ai_title_label():
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "ai_title_trace.jsonl"
    t = parse(fix)
    assert t.label == "My Custom Session Title"


def test_parse_label_none_when_no_ai_title():
    """The minimal fixture has no ai-title event."""
    t = parse(FIX)  # FIX is the existing minimal_trace.jsonl path constant
    assert t.label is None


def test_parse_absorbs_tools_changed_as_assistant():
    """tools_changed events carry real assistant messages with their own usage."""
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "tools_changed_trace.jsonl"
    t = parse(fix)
    # Three assistant turns
    assistant_turns = [tr for tr in t.turns if tr.role == "assistant"]
    assert len(assistant_turns) == 3
    # Total output: 5 + 100 + 7 = 112 (was 12 in v0.2 because tools_changed was skipped)
    total_output = sum(tr.usage.output_tokens for tr in assistant_turns if tr.usage)
    assert total_output == 112
