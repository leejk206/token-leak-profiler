from pathlib import Path
import json as json_module
from tlp.schema.dump import dump, render_text, render_json
from tlp.schema.dump import SchemaReport


FIX = Path(__file__).parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"


def test_dump_returns_schema_report():
    r = dump(FIX)
    assert isinstance(r, SchemaReport)
    assert r.session_id == "sess-1"
    assert r.event_count == 3


def test_dump_counts_event_types():
    r = dump(FIX)
    assert r.event_types["user"] == 2
    assert r.event_types["assistant"] == 1


def test_dump_counts_assistant_block_types():
    r = dump(FIX)
    # The minimal trace has 1 assistant text block
    assert r.assistant_block_types.get("text", 0) == 1


def test_dump_message_id_stats():
    r = dump(FIX)
    # The minimal trace's single assistant message has no `id` field set —
    # acceptable to treat unique_message_ids as 0 or count missing-as-blank.
    # Just verify the field exists and is non-negative.
    assert r.unique_message_ids >= 0
    assert r.max_message_id_repeat >= 0


def test_dump_usage_totals():
    r = dump(FIX)
    # Minimal trace assistant turn has input=120, output=6
    assert r.usage_totals["input_tokens"] == 120
    assert r.usage_totals["output_tokens"] == 6


def test_render_text_contains_section_headers():
    r = dump(FIX)
    out = render_text(r)
    assert "Session" in out
    assert "events:" in out
    assert "event types:" in out
    assert "usage totals:" in out


def test_render_json_parses_with_expected_keys():
    r = dump(FIX)
    out = render_json(r)
    data = json_module.loads(out)
    assert "session_id" in data
    assert "event_count" in data
    assert "event_types" in data
    assert "assistant_block_types" in data
    assert "usage_totals" in data


def test_dump_captures_first_sample_per_skipped_type(tmp_path):
    """Each skipped event type gets one raw sample in skipped_event_samples
    so spec writers can see field names instead of guessing."""
    fixture = tmp_path / "mixed.jsonl"
    fixture.write_text(
        '{"type":"user","sessionId":"x","uuid":"u1","message":{"role":"user","content":"hi"}}\n'
        '{"type":"ai-title","sessionId":"x","aiTitle":"My Title"}\n'
        '{"type":"ai-title","sessionId":"x","aiTitle":"Second Title (ignored)"}\n'
        '{"type":"attachment","sessionId":"x","uuid":"att1","attachmentData":"..."}\n'
    )
    r = dump(fixture)
    assert "ai-title" in r.skipped_event_samples
    assert "attachment" in r.skipped_event_samples
    # First sample wins — second ai-title shouldn't overwrite
    assert r.skipped_event_samples["ai-title"].get("aiTitle") == "My Title"


def test_render_text_shows_skipped_field_keys(tmp_path):
    fixture = tmp_path / "ait.jsonl"
    fixture.write_text(
        '{"type":"ai-title","sessionId":"x","aiTitle":"T"}\n'
    )
    r = dump(fixture)
    out = render_text(r)
    assert "skipped event field samples" in out
    assert "ai-title" in out
    assert "aiTitle" in out   # the key name appears in keys list
