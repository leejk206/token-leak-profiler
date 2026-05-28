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
