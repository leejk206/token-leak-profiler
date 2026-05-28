# Token Leak Profiler v0.7.0 Implementation Plan

> Use subagent-driven-development. 5 tasks.

**Goal:** BaseAnalyzer metadata enforcement + rule self-application pytest + mcp_server_overhead partial use + measurements.yaml promotion path.

**Spec:** [v0.7-design.md](../specs/2026-05-29-token-leak-profiler-v0.7-design.md)

---

## Task 1: types + BaseAnalyzer metadata

**Files:** tlp/types.py, tlp/analyzers/base.py, tests/test_analyzers/test_base.py

- [ ] **Step 1: Failing test**

Append to `tests/test_analyzers/test_base.py`:

```python
def test_subclass_missing_prescription_raises():
    from tlp.analyzers.base import BaseAnalyzer
    from tlp.types import LeverCategory, LeakReport
    with pytest.raises(TypeError, match="prescription"):
        class _BadA(BaseAnalyzer):
            name = "_bad_a"
            lever = LeverCategory.STALE_CONTEXT
            usage_bucket = "input"
            measurement_basis = "measured"
            def analyze(self, trace, config):
                return LeakReport(analyzer=self.name, lever=self.lever,
                                  leaked_tokens=0, leaked_cost_usd=0.0, findings=[])


def test_subclass_missing_measurement_basis_raises():
    from tlp.analyzers.base import BaseAnalyzer
    from tlp.types import LeverCategory, LeakReport
    with pytest.raises(TypeError, match="measurement_basis"):
        class _BadB(BaseAnalyzer):
            name = "_bad_b"
            lever = LeverCategory.STALE_CONTEXT
            usage_bucket = "input"
            prescription = "do x"
            def analyze(self, trace, config):
                return LeakReport(analyzer=self.name, lever=self.lever,
                                  leaked_tokens=0, leaked_cost_usd=0.0, findings=[])


def test_subclass_invalid_measurement_basis_raises():
    from tlp.analyzers.base import BaseAnalyzer
    from tlp.types import LeverCategory, LeakReport
    with pytest.raises(TypeError, match="measurement_basis"):
        class _BadC(BaseAnalyzer):
            name = "_bad_c"
            lever = LeverCategory.STALE_CONTEXT
            usage_bucket = "input"
            prescription = "do x"
            measurement_basis = "bogus"   # invalid
            def analyze(self, trace, config):
                return LeakReport(analyzer=self.name, lever=self.lever,
                                  leaked_tokens=0, leaked_cost_usd=0.0, findings=[])
```

Make sure `import pytest` is present in the test file.

- [ ] **Step 2: Run failing**

```bash
uv run pytest tests/test_analyzers/test_base.py -v
```

Expected: 3 tests FAIL.

- [ ] **Step 3: Modify tlp/types.py**

Add Literal:
```python
MeasurementBasis = Literal["measured", "estimated", "heuristic"]
```

- [ ] **Step 4: Modify tlp/analyzers/base.py**

Add ClassVar requirements + enforcement in `__init_subclass__`. The existing `__init_subclass__` already checks `name`, `lever`, `usage_bucket`. Extend it:

```python
class BaseAnalyzer:
    name: ClassVar[str]
    lever: ClassVar[LeverCategory]
    usage_bucket: ClassVar[UsageBucket]
    prescription: ClassVar[str | None]
    measurement_basis: ClassVar[MeasurementBasis]

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        for attr in ("name", "lever", "usage_bucket", "prescription", "measurement_basis"):
            if not hasattr(cls, attr):
                raise TypeError(f"{cls.__name__} missing required class attribute: {attr}")
        # Allow prescription to be None (signal-only). Validate measurement_basis value.
        if cls.measurement_basis not in ("measured", "estimated", "heuristic"):
            raise TypeError(
                f"{cls.__name__}.measurement_basis must be 'measured', 'estimated', or 'heuristic'; "
                f"got {cls.measurement_basis!r}"
            )
        registry.register(cls)
```

Make sure `MeasurementBasis` is imported from tlp.types.

- [ ] **Step 5: Run tests + full suite**

```bash
uv run pytest tests/test_analyzers/test_base.py -v
uv run pytest -q
```

Expected: new tests pass, BUT existing analyzers now fail to register because they don't declare prescription/measurement_basis. Task 2 fixes that.

If full suite breaks: that's expected. Task 2 will fix.

- [ ] **Step 6: Commit (allowed to be broken until T2)**

Skip commit; do T2 first to restore green, then single combined commit at end of T2.

---

## Task 2: Annotate all 10 existing analyzers with metadata

**Files:** all 10 files under tlp/analyzers/ (except base.py and _helpers.py)

- [ ] **Step 1: Apply metadata table from spec §5**

For each analyzer file, add the two ClassVars right after the existing ones:

`stale_context.py`:
```python
class StaleContextAnalyzer(BaseAnalyzer):
    name = "stale_context"
    lever = LeverCategory.STALE_CONTEXT
    usage_bucket = "input"
    prescription = None
    measurement_basis = "measured"
```

`redundant_restatement.py`:
```python
    prescription = "Move duplicate text to system prompt"
    measurement_basis = "measured"
```

`verbose_tool_results.py`:
```python
    prescription = None
    measurement_basis = "measured"
```

`reasoning_overrun.py`:
```python
    prescription = None
    measurement_basis = "measured"
```

`format_boilerplate.py`:
```python
    prescription = "Add 'no preamble' to system prompt or stop sequence"
    measurement_basis = "measured"
```

`cache_turnover_cost.py`:
```python
    prescription = "Reduce idle time below 5 min (recoverable findings)"
    measurement_basis = "measured"
```

`subagent_context_overdump.py`:
```python
    prescription = "Narrow Agent dispatch prompt scope on next call"
    measurement_basis = "measured"
```

`system_prompt_audit.py`:
```python
    prescription = None
    measurement_basis = "measured"
```

`roundtrip_inflation.py`:
```python
    prescription = None
    measurement_basis = "measured"
```

`tool_result_repetition.py`:
```python
    prescription = None
    measurement_basis = "measured"
```

`mcp_server_overhead.py`:
```python
    prescription = "Disable unused MCP server in Claude Code settings (~/.claude/claude.json)"
    measurement_basis = "estimated"
```

- [ ] **Step 2: Run full suite**

```bash
uv run pytest -q
```

Expected: all 144 pass + 3 new from Task 1 = 147 passing.

- [ ] **Step 3: Commit T1 + T2 together**

```bash
git add tlp/types.py tlp/analyzers/base.py tlp/analyzers/*.py tests/test_analyzers/test_base.py
git commit -m "feat(analyzers): BaseAnalyzer prescription + measurement_basis ClassVar enforcement"
```

---

## Task 3: Rule self-application pytest

**Files:** tests/test_rules_self_application.py (NEW)

- [ ] **Step 1: Create the test file**

`tests/test_rules_self_application.py`:

```python
"""Self-applies spec-checklist rules 5 and 6 to every registered analyzer.

Failing this test means a new analyzer was added without declaring its
metadata or its declarations contradict the output it produces.
"""
from __future__ import annotations
import pytest
from tlp.analyzers import registry


_REGISTERED = registry.all()


@pytest.mark.parametrize("cls", _REGISTERED, ids=[c.name for c in _REGISTERED])
def test_analyzer_declares_metadata(cls):
    """Rule 5/6 prerequisite."""
    assert hasattr(cls, "prescription"), f"{cls.__name__} missing prescription ClassVar"
    assert hasattr(cls, "measurement_basis"), f"{cls.__name__} missing measurement_basis ClassVar"
    assert cls.measurement_basis in ("measured", "estimated", "heuristic"), \
        f"{cls.__name__}.measurement_basis must be measured/estimated/heuristic"


@pytest.mark.parametrize("cls", _REGISTERED, ids=[c.name for c in _REGISTERED])
def test_rule_5_prescription_present_when_confirmed_possible(cls):
    """Rule 5: measured analyzers must declare a non-empty prescription
    (since they can emit confirmed findings)."""
    if cls.measurement_basis == "measured":
        # measured analyzers must have a non-empty prescription string
        # (cache_turnover_cost emits both confirmed and signal; prescription
        # covers the confirmed/recoverable path)
        if cls.prescription is None:
            pytest.fail(
                f"{cls.__name__} declares measured basis but lacks prescription; "
                f"rule 5 requires actionable prescription for confirmed-emitting analyzers"
            )
        assert isinstance(cls.prescription, str) and cls.prescription.strip(), \
            f"{cls.__name__}.prescription must be a non-empty string"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_rules_self_application.py -v
```

Expected: all parametrized cases pass (11 analyzers × 2 tests = 22 cases).

- [ ] **Step 3: Run full suite**

```bash
uv run pytest -q
```

Expected: ~169 passed (147 + 22).

- [ ] **Step 4: Commit**

```bash
git add tests/test_rules_self_application.py
git commit -m "test: rule 5/6 self-application across all registered analyzers"
```

---

## Task 4: measurements.yaml loader + mcp_server_overhead promotion path

**Files:** tlp/config/measurements.yaml (NEW), tlp/config/__init__.py, tlp/analyzers/mcp_server_overhead.py, tests/test_analyzers/test_mcp_server_overhead.py, tests/fixtures/synthetic/mcp_measured_trace.jsonl

- [ ] **Step 1: Create empty measurements.yaml**

`tlp/config/measurements.yaml`:

```yaml
# Tool → measured token count.
# Optional. Empty by default. Populate by running Anthropic count_tokens API
# against tool definitions and recording results here. Community can share.
#
# When mcp_server_overhead finds all tools of a server defined here, the
# server's Finding promotes from evidence_kind="estimated" to "confirmed".

tools: {}
  # Example (uncomment + populate):
  # mcp__playwright__browser_click: 187
  # mcp__pal__chat: 412
```

- [ ] **Step 2: Add load_measurements to tlp/config/__init__.py**

Append:

```python
_MEASUREMENTS_PATH = _HERE / "measurements.yaml"


def load_measurements(override: Path | None = None) -> dict[str, int]:
    path = override or _MEASUREMENTS_PATH
    if not path.exists():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return {k: int(v) for k, v in (data.get("tools") or {}).items()}
```

- [ ] **Step 3: Write failing tests for promotion path**

Append to `tests/test_analyzers/test_mcp_server_overhead.py`:

```python
import tempfile, json as json_module
import yaml as yaml_module


def test_measurements_yaml_promotes_to_confirmed(tmp_path):
    """When all tools of an unused server are in measurements.yaml,
    Finding evidence_kind promotes to confirmed."""
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
    # Inject measurements into config or load directly; analyzer must accept override.
    # For test simplicity, monkey-patch config:
    measurements = load_measurements(measurements_path)
    config["__measurements"] = measurements  # convention: analyzer reads this if present

    r = MCPServerOverheadAnalyzer().analyze(trace, config)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence_kind == "confirmed"   # promoted
    assert f.leaked_tokens == 50 + 60 + 70   # measured sum
    assert f.evidence["measurement_basis"] == "measured"


def test_measurements_partial_coverage_stays_estimated(tmp_path):
    """Mixed: some tools measured, some not → stays estimated, basis='mixed'."""
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
        "tools": {"mcp__mix__a": 50}   # only 1 of 3
    }))

    from tlp.parser import parse
    from tlp.config import load_defaults, load_measurements

    trace = parse(trace_path)
    config = load_defaults()
    config["__measurements"] = load_measurements(measurements_path)

    r = MCPServerOverheadAnalyzer().analyze(trace, config)
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.evidence_kind == "estimated"   # not promoted
    assert f.leaked_tokens == 50 + 200 + 200   # 1 measured + 2 heuristic
    assert f.evidence["measurement_basis"] == "mixed"
```

- [ ] **Step 4: Run failing**

```bash
uv run pytest tests/test_analyzers/test_mcp_server_overhead.py -v -k "measurements"
```

Expected: FAIL (mcp_server_overhead doesn't read __measurements yet).

- [ ] **Step 5: Modify mcp_server_overhead.py to use measurements**

In the `analyze` method, just before computing `leaked` for each unused server, read measurements from config:

```python
        measurements = config.get("__measurements", {})
        # ... server iteration ...
        for server, activated_set in sorted(server_to_activated.items()):
            called_count = len(activated_set & called_names)
            if called_count > 0:
                continue
            covered = [t for t in activated_set if t in measurements]
            coverage = len(covered) / len(activated_set) if activated_set else 0
            if coverage == 1.0:
                leaked = sum(measurements[t] for t in activated_set)
                basis = "measured"
                evidence_kind = "confirmed"
            elif coverage > 0:
                leaked = sum(measurements[t] for t in covered) + (len(activated_set) - len(covered)) * est_per_tool
                basis = "mixed"
                evidence_kind = "estimated"
            else:
                leaked = len(activated_set) * est_per_tool
                basis = "heuristic"
                evidence_kind = "estimated"
            # ... emit Finding with evidence dict including measurement_basis ...
```

Add to evidence dict:
```python
"measurement_basis": basis,
"measurement_coverage_ratio": round(coverage, 3),
```

Pass `evidence_kind=evidence_kind` to Finding (instead of hardcoded "estimated").

- [ ] **Step 6: Run tests + full suite**

```bash
uv run pytest tests/test_analyzers/test_mcp_server_overhead.py -v
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tlp/config/measurements.yaml tlp/config/__init__.py tlp/analyzers/mcp_server_overhead.py tests/test_analyzers/test_mcp_server_overhead.py
git commit -m "feat(mcp_server_overhead): measurements.yaml promotes finding to confirmed"
```

---

## Task 5: Partial use granularity + version + docs

**Files:** tlp/analyzers/mcp_server_overhead.py, tlp/config/defaults.yaml, tests/fixtures/synthetic/mcp_partial_use_trace.jsonl, tests/test_analyzers/test_mcp_server_overhead.py, tlp/__init__.py, pyproject.toml, README.md, docs/spec-checklist.md

- [ ] **Step 1: Add config**

In `tlp/config/defaults.yaml`, in the `mcp_server_overhead` block, add:

```yaml
mcp_server_overhead:
  estimated_tokens_per_tool_def: 200
  min_use_ratio: 0.3
```

- [ ] **Step 2: Write fixture for partial use**

`tests/fixtures/synthetic/mcp_partial_use_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"part","uuid":"u1","attachment":{"type":"deferred_tools_delta","addedNames":["mcp__demo__a","mcp__demo__b","mcp__demo__c","mcp__demo__d","mcp__demo__e"]},"message":{"role":"user","content":"start"}}
{"type":"assistant","sessionId":"part","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"tool_use","id":"tu_1","name":"mcp__demo__a","input":{}}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"part","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"ok"}]}}
```

1 of 5 tools called (20% < 30% min_use_ratio threshold) → partial-use Finding for the 4 unused.

- [ ] **Step 3: Write failing tests**

Append to `tests/test_analyzers/test_mcp_server_overhead.py`:

```python
PARTIAL_FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "mcp_partial_use_trace.jsonl"


def test_partial_use_below_min_ratio_flagged():
    trace = parse(PARTIAL_FIX)
    r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
    # demo server: 5 tools, 1 called → 20% use < 30% threshold → 4 unused flagged
    assert len(r.findings) == 1
    f = r.findings[0]
    assert ".partial" in f.location
    assert "4/5" in f.location
    assert f.leaked_tokens == 4 * 200   # 4 unused tools × heuristic 200


def test_partial_use_above_min_ratio_ignored():
    """3 of 5 called (60%) → above threshold → no Finding."""
    import tempfile, json as json_module
    events = [
        {"type":"user","sessionId":"x","uuid":"u1",
         "attachment":{"type":"deferred_tools_delta","addedNames":["mcp__demo__a","mcp__demo__b","mcp__demo__c","mcp__demo__d","mcp__demo__e"]},
         "message":{"role":"user","content":"start"}},
        {"type":"assistant","sessionId":"x","uuid":"a1",
         "message":{"role":"assistant","id":"m1",
                    "content":[{"type":"tool_use","id":"tu_1","name":"mcp__demo__a","input":{}}],
                    "usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
        {"type":"user","sessionId":"x","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"ok"}]}},
        {"type":"assistant","sessionId":"x","uuid":"a2",
         "message":{"role":"assistant","id":"m2",
                    "content":[{"type":"tool_use","id":"tu_2","name":"mcp__demo__b","input":{}}],
                    "usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
        {"type":"user","sessionId":"x","uuid":"u3","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_2","content":"ok"}]}},
        {"type":"assistant","sessionId":"x","uuid":"a3",
         "message":{"role":"assistant","id":"m3",
                    "content":[{"type":"tool_use","id":"tu_3","name":"mcp__demo__c","input":{}}],
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
```

- [ ] **Step 4: Modify mcp_server_overhead.py for partial-use**

In the existing loop where `called_count > 0` currently `continue`s, add the partial-use branch:

```python
        c = config.get("mcp_server_overhead", {})
        est_per_tool = int(c.get("estimated_tokens_per_tool_def", 200))
        min_use_ratio = float(c.get("min_use_ratio", 0.3))

        # ... existing logic ...
        for server, activated_set in sorted(server_to_activated.items()):
            used_set = activated_set & called_names
            used_count = len(used_set)
            total_count = len(activated_set)

            if used_count == 0:
                # Server-level unused (existing v0.6 path with measurements promotion)
                # ... existing code ...
                pass

            elif used_count / total_count < min_use_ratio:
                # Partial use — flag the unused subset
                unused_subset = activated_set - called_names
                unused_count = len(unused_subset)
                # Apply same measurements logic for unused_subset
                covered = [t for t in unused_subset if t in measurements]
                coverage = len(covered) / unused_count if unused_count else 0
                if coverage == 1.0:
                    leaked = sum(measurements[t] for t in unused_subset)
                    basis = "measured"
                    evidence_kind = "confirmed"
                elif coverage > 0:
                    leaked = sum(measurements[t] for t in covered) + (unused_count - len(covered)) * est_per_tool
                    basis = "mixed"
                    evidence_kind = "estimated"
                else:
                    leaked = unused_count * est_per_tool
                    basis = "heuristic"
                    evidence_kind = "estimated"
                confidence = "high" if unused_count >= 10 else "mid"
                findings.append(Finding(
                    location=f"mcp_server[{server}].partial({unused_count}/{total_count})",
                    leaked_tokens=leaked,
                    confidence=confidence,
                    suggestion=(
                        f"MCP server '{server}' has {used_count}/{total_count} tools used "
                        f"this session; {unused_count} unused. Estimated overhead from unused "
                        f"subset: {leaked} tok. Inspect whether the unused tools warrant "
                        f"disabling the server or pruning at the tool level."
                    ),
                    evidence={
                        "server_name": server,
                        "total_tool_count": total_count,
                        "used_count": used_count,
                        "unused_count": unused_count,
                        "measurement_basis": basis,
                        "measurement_coverage_ratio": round(coverage, 3),
                    },
                    evidence_kind=evidence_kind,
                ))
                total += leaked
```

(Refactor the existing server-level path to share variables `measurements`, `basis`, `evidence_kind` cleanly.)

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_analyzers/test_mcp_server_overhead.py -v
uv run pytest -q
```

- [ ] **Step 6: Version + docs**

`tlp/__init__.py`: `__version__ = "0.7.0"`
`pyproject.toml`: `version = "0.7.0"`

`README.md`:
- Add a sub-line under the lever catalog: "MCP partial-use sub-case: server with <30% tools used → unused subset flagged."
- Add a line under v0.6.1 evidence model note: "`measurements.yaml` (optional) lets you promote estimated MCP findings to confirmed by supplying empirically-measured tool token counts."

`docs/spec-checklist.md`:
- Under Rule 5 and Rule 6, add a line: "**Enforced by:** `tests/test_rules_self_application.py`."

- [ ] **Step 7: Final ruff + full suite**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: ~175 pass, ruff clean.

- [ ] **Step 8: Commit + push**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(v0.7.0): mcp partial-use + measurements.yaml + rule self-application

- mcp_server_overhead: partial-use sub-case (server with <30% tools used flags unused subset)
- measurements.yaml: optional empirical tool token counts; promotes finding to confirmed
- BaseAnalyzer: prescription + measurement_basis ClassVar enforcement
- tests/test_rules_self_application.py: rules 5/6 automated across all registered analyzers
- spec-checklist: rules cite the enforcement test

Closes Council R2 (Red Team Scenario B) — partial use no longer invisible.
Closes v0.6 backlog estimated→confirmed promotion path.
Closes 8th-recurrence prevention mechanism (rule self-application).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

## Report

Status, files, test count, version, git log -3.
