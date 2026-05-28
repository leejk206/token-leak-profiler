from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.tool_result_repetition import ToolResultRepetitionAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "tool_repeat_trace.jsonl"


def test_flags_repeated_identical_tool_call():
    trace = parse(FIX)
    r = ToolResultRepetitionAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert "Read" in f.location
    assert f.evidence["repeat_count"] == 2
    assert f.evidence_kind == "signal"
    assert f.confidence == "low"


def test_no_finding_when_unique_calls():
    import tempfile, json as json_module
    events = [
        {"type":"assistant","message":{"role":"assistant","id":"m1","content":[{"type":"tool_use","id":"t1","name":"Read","input":{"path":"a.txt"}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
        {"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"A"}]}},
        {"type":"assistant","message":{"role":"assistant","id":"m2","content":[{"type":"tool_use","id":"t2","name":"Read","input":{"path":"b.txt"}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
        {"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t2","content":"B"}]}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        trace = parse(path)
        r = ToolResultRepetitionAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()
