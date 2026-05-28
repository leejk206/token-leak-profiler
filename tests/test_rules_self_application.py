"""Self-applies spec-checklist rules 5 and 6 to every registered analyzer.

Failing this test means a new analyzer was added without declaring its
metadata or its declarations contradict the output it produces.

Rule 5 (measurement→action 1:1): analyzers with measurement_basis == "measured"
must have non-empty prescription string, because "measured" means the analyzer
emits confirmed Findings with proven waste — and every confirmed Finding requires
an actionable prescription.

Rule 6 (measurement vs model-output): all analyzers must declare measurement_basis
in {"measured", "estimated", "heuristic"}.

Metadata adjustment note (2026-05-29):
    The following analyzers were originally declared measurement_basis="measured"
    but were changed to measurement_basis="heuristic" because they emit only
    evidence_kind="signal" Findings — never "confirmed". They count/measure tokens,
    but cannot prove the tokens were wasted without human review (heuristic-level
    confidence). Rule 5 requires prescription only when waste is confirmed, so
    these analyzers correctly carry prescription=None and measurement_basis="heuristic":
      - stale_context
      - verbose_tool_results
      - reasoning_overrun
      - system_prompt_audit
      - roundtrip_inflation
      - tool_result_repetition
"""
from __future__ import annotations
import pytest
from tlp.analyzers import registry


_REGISTERED = registry.all()


@pytest.mark.parametrize("cls", _REGISTERED, ids=[c.name for c in _REGISTERED])
def test_analyzer_declares_metadata(cls):
    """Rule 5/6 prerequisite: every registered analyzer carries required metadata."""
    assert hasattr(cls, "prescription"), f"{cls.__name__} missing prescription ClassVar"
    assert hasattr(cls, "measurement_basis"), f"{cls.__name__} missing measurement_basis ClassVar"
    assert cls.measurement_basis in ("measured", "estimated", "heuristic"), (
        f"{cls.__name__}.measurement_basis must be measured/estimated/heuristic, "
        f"got {cls.measurement_basis!r}"
    )


@pytest.mark.parametrize("cls", _REGISTERED, ids=[c.name for c in _REGISTERED])
def test_rule_5_prescription_present_when_measured(cls):
    """Rule 5: measured analyzers emit confirmed Findings, which require a
    non-empty actionable prescription string.

    Analyzers that produce only signal-level Findings should declare
    measurement_basis='heuristic' instead of 'measured', so that this rule
    correctly skips them.
    """
    if cls.measurement_basis == "measured":
        if cls.prescription is None:
            pytest.fail(
                f"{cls.__name__} declares measurement_basis='measured' but lacks prescription; "
                f"rule 5 requires actionable prescription for confirmed-emitting analyzers. "
                f"If this analyzer emits only signal Findings, change measurement_basis to 'heuristic'."
            )
        assert isinstance(cls.prescription, str) and cls.prescription.strip(), (
            f"{cls.__name__}.prescription must be a non-empty string; "
            f"got {cls.prescription!r}"
        )
