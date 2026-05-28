from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.system_prompt_audit import SystemPromptAuditAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "system_prompt_audit_trace.jsonl"


def test_flags_large_stable_prefix():
    trace = parse(FIX)
    r = SystemPromptAuditAnalyzer().analyze(trace, load_defaults())
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.location == "system_prompt"
    assert f.evidence_kind == "signal"
    assert f.confidence == "low"
    assert f.leaked_tokens == 7000  # 17000 - 10000 baseline
    assert f.evidence["stable_prefix_tokens"] == 17000


def test_no_finding_below_threshold():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = SystemPromptAuditAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_on_subagent():
    sub = Path(__file__).parent.parent / "fixtures" / "synthetic" / "subagent_overdump_trace.jsonl"
    trace = parse(sub)
    r = SystemPromptAuditAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
