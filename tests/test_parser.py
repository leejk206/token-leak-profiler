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
