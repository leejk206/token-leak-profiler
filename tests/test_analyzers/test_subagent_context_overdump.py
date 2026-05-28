from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.subagent_context_overdump import SubagentContextOverdumpAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "subagent_overdump_trace.jsonl"


def test_flags_large_subagent_first_prompt():
    trace = parse(FIX)
    assert trace.is_subagent is True
    r = SubagentContextOverdumpAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.location == "subagent_prompt"
    assert f.evidence_kind == "confirmed"


def test_no_finding_on_non_subagent_trace():
    minimal = Path(__file__).parent.parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"
    trace = parse(minimal)
    r = SubagentContextOverdumpAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_below_threshold():
    import tempfile, json as json_module
    fixture = (
        json_module.dumps({"isSidechain": True, "agentId": "agent-y", "type": "user",
                           "message": {"role": "user", "content": "small task"}}) + "\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(fixture)
        path = Path(f.name)
    try:
        trace = parse(path)
        r = SubagentContextOverdumpAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()
