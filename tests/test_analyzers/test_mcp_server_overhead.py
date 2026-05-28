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
    assert f.evidence_kind == "estimated"
    assert f.evidence["measurement_basis"] == "heuristic"
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


import json as json_module
import yaml as yaml_module


def test_measurements_yaml_promotes_to_confirmed(tmp_path):
    """When all tools of an unused server are in measurements.yaml,
    Finding evidence_kind promotes to confirmed and uses measured sum."""
    fixture = (
        json_module.dumps({"type":"user","sessionId":"x","uuid":"u1",
                           "attachment":{"type":"deferred_tools_delta",
                                          "addedNames":["mcp__small__a","mcp__small__b","mcp__small__c"]},
                           "message":{"role":"user","content":"start"}}) + "\n"
        + json_module.dumps({"type":"assistant","sessionId":"x","uuid":"a1",
                             "message":{"role":"assistant","id":"m1",
                                        "content":[{"type":"text","text":"ok"}],
                                        "usage":{"input_tokens":1,"output_tokens":1,
                                                 "cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}) + "\n"
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(fixture)

    measurements_path = tmp_path / "measurements.yaml"
    measurements_path.write_text(yaml_module.safe_dump({
        "tools": {"mcp__small__a": 50, "mcp__small__b": 60, "mcp__small__c": 70}
    }))

    from tlp.parser import parse
    from tlp.config import load_defaults, load_measurements

    trace = parse(trace_path)
    config = load_defaults()
    config["__measurements"] = load_measurements(measurements_path)

    r = MCPServerOverheadAnalyzer().analyze(trace, config)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence_kind == "confirmed"
    assert f.leaked_tokens == 50 + 60 + 70
    assert f.evidence["measurement_basis"] == "measured"


def test_measurements_partial_coverage_stays_estimated(tmp_path):
    """Mixed coverage → stays estimated; basis='mixed'."""
    fixture = (
        json_module.dumps({"type":"user","sessionId":"x","uuid":"u1",
                           "attachment":{"type":"deferred_tools_delta",
                                          "addedNames":["mcp__mix__a","mcp__mix__b","mcp__mix__c"]},
                           "message":{"role":"user","content":"start"}}) + "\n"
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(fixture)

    measurements_path = tmp_path / "measurements.yaml"
    measurements_path.write_text(yaml_module.safe_dump({
        "tools": {"mcp__mix__a": 50}
    }))

    from tlp.parser import parse
    from tlp.config import load_defaults, load_measurements

    trace = parse(trace_path)
    config = load_defaults()
    config["__measurements"] = load_measurements(measurements_path)

    r = MCPServerOverheadAnalyzer().analyze(trace, config)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence_kind == "estimated"
    assert f.leaked_tokens == 50 + 200 + 200
    assert f.evidence["measurement_basis"] == "mixed"


def test_measurements_empty_stays_estimated(tmp_path):
    """No measurements → 'heuristic' basis preserved (current default behavior)."""
    fixture = (
        json_module.dumps({"type":"user","sessionId":"x","uuid":"u1",
                           "attachment":{"type":"deferred_tools_delta",
                                          "addedNames":["mcp__none__a","mcp__none__b"]},
                           "message":{"role":"user","content":"start"}}) + "\n"
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(fixture)

    from tlp.parser import parse
    from tlp.config import load_defaults

    trace = parse(trace_path)
    config = load_defaults()  # no __measurements

    r = MCPServerOverheadAnalyzer().analyze(trace, config)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence_kind == "estimated"
    assert f.leaked_tokens == 2 * 200
    assert f.evidence["measurement_basis"] == "heuristic"


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
