from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.mcp_server_overhead import MCPServerOverheadAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "mcp_unused_trace.jsonl"


def test_flags_unused_mcp_server():
    trace = parse(FIX)
    r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert "demo" in f.location
    assert f.leaked_tokens == 1000  # 5 × 200
    assert f.evidence_kind == "confirmed"
    assert f.evidence["activated_tool_count"] == 5
    assert f.evidence["called_count"] == 0


def test_no_finding_when_called_at_least_once():
    import tempfile
    import json as json_module
    events = [
        {"type":"user","sessionId":"x","uuid":"u1",
         "attachment":{"type":"deferred_tools_delta","addedNames":["mcp__demo__a","mcp__demo__b"]},
         "message":{"role":"user","content":"hi"}},
        {"type":"assistant","sessionId":"x","uuid":"a1",
         "message":{"role":"assistant","id":"m1",
                    "content":[{"type":"tool_use","id":"tu_1","name":"mcp__demo__a","input":{}}],
                    "usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        trace = parse(path)
        r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()


def test_no_finding_when_no_activations():
    minimal = Path(__file__).parent.parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"
    trace = parse(minimal)
    r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_non_mcp_tools_ignored():
    import tempfile
    import json as json_module
    events = [
        {"type":"user","sessionId":"x","uuid":"u1",
         "attachment":{"type":"deferred_tools_delta","addedNames":["Bash","TaskUpdate","Edit"]},
         "message":{"role":"user","content":"hi"}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        trace = parse(path)
        r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()
