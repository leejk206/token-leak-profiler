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


def test_lever_category_values():
    assert LeverCategory.STALE_CONTEXT.value == "stale_context"
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
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
