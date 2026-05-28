import pytest
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.types import (
    LeverCategory, LeakReport, ParsedTrace, PricingTable,
)


@pytest.fixture
def empty_trace():
    return ParsedTrace(
        session_id="s", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )


def test_subclass_auto_registers():
    initial = set(registry.names())

    class _DummyA(BaseAnalyzer):
        name = "_dummy_a"
        lever = LeverCategory.STALE_CONTEXT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

    assert "_dummy_a" in registry.names()
    assert "_dummy_a" not in initial
    registry.unregister("_dummy_a")


def test_analyze_returns_leak_report(empty_trace):
    class _DummyB(BaseAnalyzer):
        name = "_dummy_b"
        lever = LeverCategory.TOOL_SCHEMA_BLOAT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=42, leaked_cost_usd=0.0, findings=[],
            )

    r = _DummyB().analyze(empty_trace, {})
    assert r.leaked_tokens == 42
    registry.unregister("_dummy_b")


def test_duplicate_name_raises():
    class _DummyC(BaseAnalyzer):
        name = "_dummy_c"
        lever = LeverCategory.STALE_CONTEXT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(analyzer=self.name, lever=self.lever, leaked_tokens=0, leaked_cost_usd=0.0, findings=[])

    with pytest.raises(ValueError, match="duplicate"):
        class _DummyC2(BaseAnalyzer):
            name = "_dummy_c"
            lever = LeverCategory.STALE_CONTEXT
            usage_bucket = "input"
            def analyze(self, trace, config):
                return LeakReport(analyzer=self.name, lever=self.lever, leaked_tokens=0, leaked_cost_usd=0.0, findings=[])

    registry.unregister("_dummy_c")
