import pytest
from dataclasses import FrozenInstanceError
from tlp.types import (
    Block, Turn, LeverCategory, LeakReport, Finding, PricingTable,
)


def test_finding_evidence_kind_default_is_confirmed():
    f = Finding(location="x", leaked_tokens=10, confidence="mid", suggestion="x")
    assert f.evidence_kind == "confirmed"


def test_finding_evidence_kind_explicit_signal():
    f = Finding(
        location="x", leaked_tokens=10, confidence="low", suggestion="x",
        evidence_kind="signal",
    )
    assert f.evidence_kind == "signal"


def test_leak_report_breakdown_properties_sum_to_total():
    r = LeakReport(
        analyzer="x", lever=LeverCategory.STALE_CONTEXT,
        leaked_tokens=100, leaked_cost_usd=0.0,
        findings=[
            Finding("a", 40, "mid", "x", {}, "confirmed"),
            Finding("b", 60, "low", "x", {}, "signal"),
        ],
    )
    assert r.confirmed_tokens == 40
    assert r.signal_tokens == 60
    assert r.confirmed_tokens + r.signal_tokens == r.leaked_tokens


def test_block_is_frozen():
    b = Block(kind="text", text="hi", tool_name=None, tool_input=None, tool_use_id=None, tokens=1)
    with pytest.raises(FrozenInstanceError):
        b.tokens = 2  # type: ignore[misc]


def test_turn_minimal_construction():
    t = Turn(index=0, role="user", blocks=(), usage=None)
    assert t.index == 0
    assert t.role == "user"


def test_lever_category_v0_6_set():
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_turnover_cost",
        "subagent_context_overdump", "system_prompt_audit",
        "roundtrip_inflation", "tool_result_repetition",
        "mcp_server_overhead",
    }


def test_finding_evidence_default_dict():
    f = Finding(location="turn[0]", leaked_tokens=10, confidence="mid", suggestion="x")
    assert f.evidence == {}


def test_leak_report_construction():
    r = LeakReport(
        analyzer="x", lever=LeverCategory.STALE_CONTEXT,
        leaked_tokens=100, leaked_cost_usd=0.0, findings=[],
    )
    assert r.leaked_tokens == 100


def test_pricing_table_per_token():
    p = PricingTable(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_read_per_mtok=0.3, cache_creation_per_mtok=3.75,
    )
    assert p.cost(1_000_000, "input") == pytest.approx(3.0)
    assert p.cost(500_000, "output") == pytest.approx(7.5)
    assert p.cost(0, "input") == 0.0


def test_parsed_trace_label_default_none():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    assert t.label is None


def test_parsed_trace_label_explicit():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
        label="my session",
    )
    assert t.label == "my session"


def test_parsed_trace_is_subagent_default_false():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    assert t.is_subagent is False


def test_parsed_trace_is_subagent_explicit_true():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
        is_subagent=True,
    )
    assert t.is_subagent is True


def test_parsed_trace_activated_tool_names_default_empty():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    assert t.activated_tool_names == frozenset()


def test_parsed_trace_activated_tool_names_explicit():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
        activated_tool_names=frozenset({"mcp__demo__a", "mcp__demo__b"}),
    )
    assert "mcp__demo__a" in t.activated_tool_names


def test_evidence_kind_estimated_value():
    from tlp.types import Finding
    f = Finding(location="x", leaked_tokens=10, confidence="high", suggestion="x",
                evidence_kind="estimated")
    assert f.evidence_kind == "estimated"


def test_leak_report_estimated_tokens_property():
    from tlp.types import LeakReport, LeverCategory, Finding
    r = LeakReport(
        analyzer="x", lever=LeverCategory.MCP_SERVER_OVERHEAD,
        leaked_tokens=200, leaked_cost_usd=0.0,
        findings=[
            Finding("a", 50, "high", "x", {}, "confirmed"),
            Finding("b", 100, "high", "x", {}, "estimated"),
            Finding("c", 50, "low", "x", {}, "signal"),
        ],
    )
    assert r.confirmed_tokens == 50
    assert r.estimated_tokens == 100
    assert r.signal_tokens == 50
