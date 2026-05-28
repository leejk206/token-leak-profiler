# Token Leak Profiler v0.5.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add 4 analyzers (subagent_context_overdump confirmed; system_prompt_audit, roundtrip_inflation, tool_result_repetition signal) + parser is_subagent + aggregate `--include-subagents` flag. Bring blog 6-lever coverage 1/6 → 5/6.

**Architecture:** v0.4 Registry + ParsedTrace + Aggregate stays. ParsedTrace gains `is_subagent` field. Cache_turnover_cost's stable_prefix calc extracts to shared helper.

**Tech Stack:** Same as v0.4.

**Spec:** [2026-05-29-token-leak-profiler-v0.5-design.md](../specs/2026-05-29-token-leak-profiler-v0.5-design.md)

---

## File Structure

```
token-leak-profiler/
  pyproject.toml                                # MODIFY: 0.4.0 → 0.5.0
  README.md                                     # MODIFY: tagline + lever catalog 6→10
  tlp/
    __init__.py                                 # MODIFY: __version__
    types.py                                    # MODIFY: 4 enum + ParsedTrace.is_subagent
    parser/
      claude_code.py                            # MODIFY: detect isSidechain/agentId → is_subagent
    analyzers/
      __init__.py                               # MODIFY: 4 imports
      _helpers.py                               # NEW: stable_prefix estimator
      cache_turnover_cost.py                    # MODIFY: use _helpers.stable_prefix
      subagent_context_overdump.py              # NEW
      system_prompt_audit.py                    # NEW
      roundtrip_inflation.py                    # NEW
      tool_result_repetition.py                 # NEW
    aggregate/
      run.py                                    # MODIFY: include_subagents kwarg
    cli.py                                      # MODIFY: aggregate --include-subagents
    config/
      defaults.yaml                             # MODIFY: 4 new blocks
  tests/
    fixtures/synthetic/
      subagent_overdump_trace.jsonl             # NEW
      system_prompt_audit_trace.jsonl           # NEW
      roundtrip_inflation_trace.jsonl           # NEW
      tool_repeat_trace.jsonl                   # NEW
    test_types.py                               # MODIFY
    test_parser.py                              # EXTEND: is_subagent detection
    test_analyzers/
      test_subagent_context_overdump.py         # NEW
      test_system_prompt_audit.py               # NEW
      test_roundtrip_inflation.py               # NEW
      test_tool_result_repetition.py            # NEW
    test_aggregate.py                           # EXTEND: subagent inclusion
    test_cli_e2e.py                             # MODIFY: 10 analyzers + flag
  docs/superpowers/
    specs/2026-05-29-token-leak-profiler-v0.5-design.md
    plans/2026-05-29-token-leak-profiler-v0.5.md
```

---

## Task 1: Data model — 4 enum values + ParsedTrace.is_subagent

**Files:**
- Modify: `tlp/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_types.py`:

```python
def test_lever_category_v0_5_set():
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_turnover_cost",
        "subagent_context_overdump", "system_prompt_audit",
        "roundtrip_inflation", "tool_result_repetition",
    }


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
```

Also remove the old `test_lever_category_values` if it exists with only 6 values, or update it to expect 10.

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_types.py -v
```

Expected: new tests FAIL (enum missing 4 values, ParsedTrace missing is_subagent).

- [ ] **Step 3: Modify `tlp/types.py`**

Find the `LeverCategory` enum and append 4 values:

```python
class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"
    CACHE_TURNOVER_COST = "cache_turnover_cost"
    SUBAGENT_CONTEXT_OVERDUMP = "subagent_context_overdump"
    SYSTEM_PROMPT_AUDIT = "system_prompt_audit"
    ROUNDTRIP_INFLATION = "roundtrip_inflation"
    TOOL_RESULT_REPETITION = "tool_result_repetition"
```

Find the `ParsedTrace` dataclass and add `is_subagent` field as the last field (after `label`):

```python
@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable
    label: str | None = None
    is_subagent: bool = False
```

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
```

Expected: most pass (other tests rely on enum/ParsedTrace; this is additive).

- [ ] **Step 5: Commit**

```bash
git add tlp/types.py tests/test_types.py
git commit -m "feat(types): 4 new LeverCategory values + ParsedTrace.is_subagent"
```

---

## Task 2: Parser is_subagent detection

**Files:**
- Modify: `tlp/parser/claude_code.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_parser.py`:

```python
def test_parse_detects_subagent_via_isSidechain():
    """Subagent transcripts have isSidechain=True on events. ParsedTrace.is_subagent must reflect."""
    import tempfile, json as json_module
    fixture = (
        json_module.dumps({"parentUuid": None, "isSidechain": True, "agentId": "agent-xyz", "type": "user",
                           "message": {"role": "user", "content": "do task X"}}) + "\n"
        + json_module.dumps({"isSidechain": True, "type": "assistant",
                             "message": {"role": "assistant", "id": "m1",
                                         "content": [{"type": "text", "text": "ok"}],
                                         "usage": {"input_tokens": 5, "output_tokens": 2,
                                                   "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}) + "\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(fixture)
        path = Path(f.name)
    try:
        t = parse(path)
        assert t.is_subagent is True
    finally:
        path.unlink()


def test_parse_default_is_subagent_false():
    """Regular session traces have no isSidechain or all False."""
    t = parse(FIX)  # the existing minimal_trace.jsonl
    assert t.is_subagent is False
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: 2 new tests FAIL (parser doesn't set is_subagent).

- [ ] **Step 3: Modify `tlp/parser/claude_code.py`**

In the `parse()` function, after initializing the other variables (around the `ai_title` initialization line), add:

```python
    is_subagent: bool = False
```

Then in the first-pass loop, immediately after parsing the event (after `event = json.loads(raw_line)` succeeds), add:

```python
        if event.get("isSidechain") is True or event.get("agentId"):
            is_subagent = True
```

This sets the flag without affecting other logic. Finally, in the `return ParsedTrace(...)` call at the bottom, add `is_subagent=is_subagent`:

```python
    return ParsedTrace(
        session_id=session_id,
        turns=tuple(turns),
        tool_defs=dict(tool_defs),
        pricing=pricing,
        label=ai_title,
        is_subagent=is_subagent,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_parser.py -v
uv run pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add tlp/parser/claude_code.py tests/test_parser.py
git commit -m "feat(parser): detect subagent transcripts via isSidechain/agentId"
```

---

## Task 3: Extract stable_prefix helper

**Files:**
- Create: `tlp/analyzers/_helpers.py`
- Modify: `tlp/analyzers/cache_turnover_cost.py`

- [ ] **Step 1: Write `tlp/analyzers/_helpers.py`**

```python
"""Shared computation helpers for analyzers."""
from __future__ import annotations
from statistics import mean, stdev


def estimate_stable_prefix(actual_cr_values: list[int]) -> int | None:
    """Given the cache_read values observed at each invalidation event,
    estimate the stable system-prompt prefix size.

    Returns the mean if all values are tightly clustered (std-dev < 1% of mean),
    else None — meaning the prefix isn't stable enough to identify.

    Requires ≥ 2 values to compute std-dev.
    """
    if len(actual_cr_values) < 2:
        return None
    m = mean(actual_cr_values)
    if m == 0:
        return None
    s = stdev(actual_cr_values)
    if s / m < 0.01:
        return int(m)
    return None
```

- [ ] **Step 2: Modify `tlp/analyzers/cache_turnover_cost.py`**

Find the existing inline stable_prefix calculation (it computes mean of actual_cr at invalidation events and checks std-dev). Replace with:

```python
from tlp.analyzers._helpers import estimate_stable_prefix

# ... in analyze(), at the point where stable_prefix_estimate is computed ...
actual_cr_values = [usages[i][1] for i, _ in invalidations]   # actual_cr at each invalidation
stable_prefix_estimate = estimate_stable_prefix(actual_cr_values)
```

Then continue using `stable_prefix_estimate` in the evidence dict as before. Behavior must be identical to v0.4.

- [ ] **Step 3: Run cache_turnover_cost tests**

```bash
uv run pytest tests/test_analyzers/test_cache_turnover_cost.py -v
uv run pytest -q
```

Expected: all pass — refactor doesn't change behavior.

- [ ] **Step 4: Commit**

```bash
git add tlp/analyzers/_helpers.py tlp/analyzers/cache_turnover_cost.py
git commit -m "refactor(analyzers): extract estimate_stable_prefix helper for reuse"
```

---

## Task 4: subagent_context_overdump analyzer (confirmed)

**Files:**
- Create: `tlp/analyzers/subagent_context_overdump.py`
- Create: `tests/fixtures/synthetic/subagent_overdump_trace.jsonl`
- Create: `tests/test_analyzers/test_subagent_context_overdump.py`
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/analyzers/__init__.py`

- [ ] **Step 1: Add config**

Edit `tlp/config/defaults.yaml`, append:

```yaml
subagent_context_overdump:
  min_subagent_prompt_tokens: 5000
  baseline_subagent_prompt_tokens: 1000
```

- [ ] **Step 2: Write fixture**

Create `tests/fixtures/synthetic/subagent_overdump_trace.jsonl` (2 lines — subagent dispatch with ~8000-token first prompt):

```jsonl
{"isSidechain":true,"agentId":"agent-xyz","type":"user","message":{"role":"user","content":"PROMPT_PLACEHOLDER"}}
{"isSidechain":true,"type":"assistant","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":5,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

For the prompt content, use a long string. Easiest: in the file write a string of 32000 characters (≈ 8000 tokens at chars/4). Replace `PROMPT_PLACEHOLDER` with `"a" * 32000` — but JSON literal can't use multiplication. Instead, write a script that generates the fixture:

Actually, the simplest: write the fixture with a string literal that's exactly 32000 characters. Use Python to generate:

```bash
python3 -c "
import json
events = [
    {'isSidechain': True, 'agentId': 'agent-xyz', 'type': 'user',
     'message': {'role': 'user', 'content': 'a' * 32000}},
    {'isSidechain': True, 'type': 'assistant',
     'message': {'role': 'assistant', 'id': 'm1',
                 'content': [{'type': 'text', 'text': 'ok'}],
                 'usage': {'input_tokens': 5, 'output_tokens': 2,
                           'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}},
]
with open('tests/fixtures/synthetic/subagent_overdump_trace.jsonl', 'w') as f:
    for e in events:
        f.write(json.dumps(e) + '\n')
print('Wrote 2 events')
"
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_subagent_context_overdump.py`:

```python
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
    """Non-subagent traces yield empty report."""
    minimal = Path(__file__).parent.parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"
    trace = parse(minimal)
    r = SubagentContextOverdumpAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_below_threshold():
    """Subagent with small first prompt → no Finding."""
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
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_subagent_context_overdump.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 5: Write `tlp/analyzers/subagent_context_overdump.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class SubagentContextOverdumpAnalyzer(BaseAnalyzer):
    name = "subagent_context_overdump"
    lever = LeverCategory.SUBAGENT_CONTEXT_OVERDUMP
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        if not trace.is_subagent:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        c = config.get("subagent_context_overdump", {})
        min_tokens = int(c.get("min_subagent_prompt_tokens", 5000))
        baseline = int(c.get("baseline_subagent_prompt_tokens", 1000))

        first_user_turn = next(
            (t for t in trace.turns if t.role == "user"), None
        )
        if first_user_turn is None:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        first_prompt_tokens = sum(
            b.tokens for b in first_user_turn.blocks if b.kind == "text"
        )
        if first_prompt_tokens < min_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        leaked = first_prompt_tokens - baseline
        confidence = "high" if first_prompt_tokens > 20000 else "mid"
        finding = Finding(
            location="subagent_prompt",
            leaked_tokens=leaked,
            confidence=confidence,
            suggestion=(
                f"Subagent dispatch prompt is {first_prompt_tokens} tok "
                f"(recommended baseline: {baseline} tok). Narrow the scope on "
                f"next dispatch — pass only specific context needed for the task."
            ),
            evidence={
                "first_prompt_tokens": first_prompt_tokens,
                "baseline": baseline,
            },
            evidence_kind="confirmed",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=leaked, leaked_cost_usd=0.0, findings=[finding],
        )
```

- [ ] **Step 6: Register in analyzers `__init__.py`**

Add `subagent_context_overdump` to the imports list:

```python
from tlp.analyzers import (  # noqa: F401
    stale_context,
    redundant_restatement,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
    cache_turnover_cost,
    subagent_context_overdump,
)
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_analyzers/test_subagent_context_overdump.py -v
uv run pytest -q
```

Expected: 3 new tests pass; full suite green.

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/subagent_context_overdump.py tlp/analyzers/__init__.py tlp/config/defaults.yaml tests/fixtures/synthetic/subagent_overdump_trace.jsonl tests/test_analyzers/test_subagent_context_overdump.py
git commit -m "feat(analyzers): subagent_context_overdump — large dispatch prompt detection"
```

---

## Task 5: system_prompt_audit analyzer (signal)

**Files:**
- Create: `tlp/analyzers/system_prompt_audit.py`
- Create: `tests/fixtures/synthetic/system_prompt_audit_trace.jsonl`
- Create: `tests/test_analyzers/test_system_prompt_audit.py`
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/analyzers/__init__.py`

- [ ] **Step 1: Add config**

Append to `tlp/config/defaults.yaml`:

```yaml
system_prompt_audit:
  min_system_prompt_tokens: 15000
  baseline_system_prompt_tokens: 10000
```

- [ ] **Step 2: Write fixture — multiple invalidation events clustering at 17k stable prefix**

Create `tests/fixtures/synthetic/system_prompt_audit_trace.jsonl` (6 lines — assistant turns with cache_read clustering at 17000 across invalidation events):

```jsonl
{"type":"user","sessionId":"sys-aud","uuid":"u0","message":{"role":"user","content":"start"}}
{"type":"assistant","sessionId":"sys-aud","uuid":"a0","message":{"role":"assistant","id":"m0","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":100,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":17000}}}
{"type":"assistant","sessionId":"sys-aud","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":17000,"cache_creation_input_tokens":3000}}}
{"type":"assistant","sessionId":"sys-aud","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":17000,"cache_creation_input_tokens":5000}}}
{"type":"assistant","sessionId":"sys-aud","uuid":"a3","message":{"role":"assistant","id":"m3","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":17000,"cache_creation_input_tokens":8000}}}
{"type":"assistant","sessionId":"sys-aud","uuid":"a4","message":{"role":"assistant","id":"m4","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":17000,"cache_creation_input_tokens":4000}}}
```

cache_read drops to 17000 at every subsequent turn → invalidation events. mean(actual_cr) = 17000, std=0. Stable prefix detected at 17000 > 15000 threshold.

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_system_prompt_audit.py`:

```python
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
    # baseline = 10000, prefix ~ 17000, so leaked ~ 7000
    assert f.leaked_tokens == 7000
    assert f.evidence["stable_prefix_tokens"] == 17000


def test_no_finding_below_threshold():
    """Trace with no clear stable prefix → empty."""
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
    """system_prompt_audit only runs on parent sessions."""
    sub = Path(__file__).parent.parent / "fixtures" / "synthetic" / "subagent_overdump_trace.jsonl"
    trace = parse(sub)
    r = SystemPromptAuditAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_system_prompt_audit.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 5: Write `tlp/analyzers/system_prompt_audit.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.analyzers._helpers import estimate_stable_prefix
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class SystemPromptAuditAnalyzer(BaseAnalyzer):
    name = "system_prompt_audit"
    lever = LeverCategory.SYSTEM_PROMPT_AUDIT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        if trace.is_subagent:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        c = config.get("system_prompt_audit", {})
        min_tokens = int(c.get("min_system_prompt_tokens", 15000))
        baseline = int(c.get("baseline_system_prompt_tokens", 10000))

        # Collect actual_cr at invalidation events (same pattern as cache_turnover_cost)
        usages = []
        first_assistant_seen = False
        for turn in trace.turns:
            if turn.role != "assistant" or turn.usage is None:
                continue
            if not first_assistant_seen:
                first_assistant_seen = True
                usages.append((turn.usage.cache_read_tokens, turn.usage.cache_creation_tokens))
                continue
            usages.append((turn.usage.cache_read_tokens, turn.usage.cache_creation_tokens))

        if len(usages) < 2:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        # Invalidation event: actual_cr < (prev_cr + prev_cc) by at least 5000
        invalidation_cr_values = []
        for i in range(1, len(usages)):
            prev_cr, prev_cc = usages[i - 1]
            actual_cr = usages[i][0]
            expected = prev_cr + prev_cc
            if expected - actual_cr >= 5000:
                invalidation_cr_values.append(actual_cr)

        stable_prefix = estimate_stable_prefix(invalidation_cr_values)
        if stable_prefix is None or stable_prefix < min_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        leaked = stable_prefix - baseline
        finding = Finding(
            location="system_prompt",
            leaked_tokens=leaked,
            confidence="low",
            suggestion=(
                f"Stable system-prompt prefix estimated at {stable_prefix} tok "
                f"(baseline: ~{baseline} tok). Skills, plugins, or MCP servers "
                f"loaded but unused contribute. Inspect /config to disable unused skills."
            ),
            evidence={
                "stable_prefix_tokens": stable_prefix,
                "baseline": baseline,
            },
            evidence_kind="signal",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=leaked, leaked_cost_usd=0.0, findings=[finding],
        )
```

- [ ] **Step 6: Register in `__init__.py`**

Add `system_prompt_audit` to the imports list:

```python
from tlp.analyzers import (  # noqa: F401
    stale_context,
    redundant_restatement,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
    cache_turnover_cost,
    subagent_context_overdump,
    system_prompt_audit,
)
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_analyzers/test_system_prompt_audit.py -v
uv run pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/system_prompt_audit.py tlp/analyzers/__init__.py tlp/config/defaults.yaml tests/fixtures/synthetic/system_prompt_audit_trace.jsonl tests/test_analyzers/test_system_prompt_audit.py
git commit -m "feat(analyzers): system_prompt_audit (signal) — stable prefix audit"
```

---

## Task 6: roundtrip_inflation analyzer (signal)

**Files:**
- Create: `tlp/analyzers/roundtrip_inflation.py`
- Create: `tests/fixtures/synthetic/roundtrip_inflation_trace.jsonl`
- Create: `tests/test_analyzers/test_roundtrip_inflation.py`
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/analyzers/__init__.py`

- [ ] **Step 1: Add config**

Append to `tlp/config/defaults.yaml`:

```yaml
roundtrip_inflation:
  short_user_msg_chars: 20
  min_short_run: 3
  estimated_assistant_response_tokens: 500
```

- [ ] **Step 2: Write fixture — 5 consecutive short user messages**

Create `tests/fixtures/synthetic/roundtrip_inflation_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"rt","uuid":"u1","message":{"role":"user","content":"ok"}}
{"type":"assistant","sessionId":"rt","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"response 1"}],"usage":{"input_tokens":10,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"rt","uuid":"u2","message":{"role":"user","content":"yes"}}
{"type":"assistant","sessionId":"rt","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"response 2"}],"usage":{"input_tokens":15,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"rt","uuid":"u3","message":{"role":"user","content":"1"}}
{"type":"assistant","sessionId":"rt","uuid":"a3","message":{"role":"assistant","id":"m3","content":[{"type":"text","text":"response 3"}],"usage":{"input_tokens":20,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"rt","uuid":"u4","message":{"role":"user","content":"go"}}
{"type":"assistant","sessionId":"rt","uuid":"a4","message":{"role":"assistant","id":"m4","content":[{"type":"text","text":"response 4"}],"usage":{"input_tokens":25,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"rt","uuid":"u5","message":{"role":"user","content":"k"}}
{"type":"assistant","sessionId":"rt","uuid":"a5","message":{"role":"assistant","id":"m5","content":[{"type":"text","text":"response 5"}],"usage":{"input_tokens":30,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

5 user turns, all under 20 chars → 1 run of length 5 ≥ min_short_run 3.

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_roundtrip_inflation.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.roundtrip_inflation import RoundtripInflationAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "roundtrip_inflation_trace.jsonl"


def test_flags_consecutive_short_user_msgs():
    trace = parse(FIX)
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    # 5 messages × 500 tok per assistant response - 500 (first is "free") = (5-1) * 500 = 2000
    assert f.leaked_tokens == 2000
    assert f.evidence_kind == "signal"
    assert f.confidence == "low"
    assert f.evidence["run_length"] == 5


def test_no_finding_below_min_run():
    """Only 2 consecutive short msgs (below min_short_run=3) → empty."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "user", (Block("text", "ok", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "r", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
            Turn(2, "user", (Block("text", "yes", None, None, None, 1),), None),
            Turn(3, "assistant", (Block("text", "r", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_long_user_msgs_break_run():
    """A long user msg in the middle breaks the run."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    long_text = "x" * 100  # > 20 chars
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "user", (Block("text", "ok", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(2, "user", (Block("text", "yes", None, None, None, 1),), None),
            Turn(3, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(4, "user", (Block("text", long_text, None, None, None, 25),), None),  # breaks run
            Turn(5, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
            Turn(6, "user", (Block("text", "k", None, None, None, 1),), None),
            Turn(7, "assistant", (Block("text", "r", None, None, None, 1),), Usage(10, 1, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RoundtripInflationAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []   # run broken; neither segment reaches 3
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_roundtrip_inflation.py -v
```

- [ ] **Step 5: Write `tlp/analyzers/roundtrip_inflation.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class RoundtripInflationAnalyzer(BaseAnalyzer):
    name = "roundtrip_inflation"
    lever = LeverCategory.ROUNDTRIP_INFLATION
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("roundtrip_inflation", {})
        short_threshold = int(c.get("short_user_msg_chars", 20))
        min_run = int(c.get("min_short_run", 3))
        est_resp = int(c.get("estimated_assistant_response_tokens", 500))

        # Iterate user turns; track runs of consecutive short ones
        runs = []
        run_start = None
        run_length = 0

        for ti, turn in enumerate(trace.turns):
            if turn.role != "user":
                continue
            text_total = sum(
                len(b.text or "")
                for b in turn.blocks
                if b.kind == "text"
            )
            if text_total < short_threshold and text_total > 0:
                if run_start is None:
                    run_start = ti
                run_length += 1
            else:
                if run_length >= min_run:
                    runs.append((run_start, ti - 1, run_length))
                run_start = None
                run_length = 0
        # close final run
        if run_length >= min_run:
            runs.append((run_start, len(trace.turns) - 1, run_length))

        if not runs:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        findings = []
        total = 0
        for start, end, length in runs:
            leaked = (length - 1) * est_resp
            total += leaked
            findings.append(Finding(
                location=f"turn[{start}..{end}]",
                leaked_tokens=leaked,
                confidence="low",
                suggestion=(
                    f"{length} consecutive short user messages (< {short_threshold} chars). "
                    f"Could have been bundled into one Plan-mode session or "
                    f"single AskUserQuestion."
                ),
                evidence={
                    "run_length": length,
                    "start_turn": start,
                    "end_turn": end,
                    "short_threshold": short_threshold,
                },
                evidence_kind="signal",
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 6: Register**

Add `roundtrip_inflation` to `tlp/analyzers/__init__.py` imports.

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_analyzers/test_roundtrip_inflation.py -v
uv run pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/roundtrip_inflation.py tlp/analyzers/__init__.py tlp/config/defaults.yaml tests/fixtures/synthetic/roundtrip_inflation_trace.jsonl tests/test_analyzers/test_roundtrip_inflation.py
git commit -m "feat(analyzers): roundtrip_inflation (signal) — short user message runs"
```

---

## Task 7: tool_result_repetition analyzer (signal)

**Files:**
- Create: `tlp/analyzers/tool_result_repetition.py`
- Create: `tests/fixtures/synthetic/tool_repeat_trace.jsonl`
- Create: `tests/test_analyzers/test_tool_result_repetition.py`
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/analyzers/__init__.py`

- [ ] **Step 1: Add config**

Append to `tlp/config/defaults.yaml`:

```yaml
tool_result_repetition:
  min_repeat: 2
```

- [ ] **Step 2: Write fixture — same Read tool called twice with same input**

Create `tests/fixtures/synthetic/tool_repeat_trace.jsonl`:

```jsonl
{"type":"assistant","sessionId":"tr","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{"path":"foo.txt"}}],"usage":{"input_tokens":10,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"tr","uuid":"u1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"file contents here line one and line two"}]}}
{"type":"assistant","sessionId":"tr","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"continuing"}],"usage":{"input_tokens":20,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","sessionId":"tr","uuid":"a3","message":{"role":"assistant","id":"m3","content":[{"type":"tool_use","id":"tu_2","name":"Read","input":{"path":"foo.txt"}}],"usage":{"input_tokens":30,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"tr","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_2","content":"file contents here line one and line two"}]}}
```

Same Read with same path → 2 calls.

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_tool_result_repetition.py`:

```python
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
    """Different inputs to same tool → no finding."""
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
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_tool_result_repetition.py -v
```

- [ ] **Step 5: Write `tlp/analyzers/tool_result_repetition.py`**

```python
from __future__ import annotations
import json
from collections import defaultdict
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class ToolResultRepetitionAnalyzer(BaseAnalyzer):
    name = "tool_result_repetition"
    lever = LeverCategory.TOOL_RESULT_REPETITION
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("tool_result_repetition", {})
        min_repeat = int(c.get("min_repeat", 2))

        # Collect (tool_name, canonical_input) → list of (tool_use_id, tool_result_tokens)
        # First pass: collect tool_use occurrences with their canonical key
        # Second pass: find matching tool_result tokens by tool_use_id
        tool_use_id_to_result_tokens = {}
        for turn in trace.turns:
            if turn.role != "tool_result":
                continue
            for b in turn.blocks:
                if b.kind == "tool_result" and b.tool_use_id:
                    tool_use_id_to_result_tokens[b.tool_use_id] = b.tokens

        # Group tool_use by (name, canonical_input)
        groups = defaultdict(list)  # key: (name, canonical_input_json) → list of tool_use_ids
        for turn in trace.turns:
            if turn.role != "assistant":
                continue
            for b in turn.blocks:
                if b.kind != "tool_use" or not b.tool_name:
                    continue
                canonical = json.dumps(b.tool_input or {}, sort_keys=True, ensure_ascii=False)
                groups[(b.tool_name, canonical)].append(b.tool_use_id)

        findings = []
        total = 0
        for (tool_name, canonical), tool_use_ids in groups.items():
            if len(tool_use_ids) < min_repeat:
                continue
            # Sum result tokens for this group; leaked = (count - 1) × per-call result
            result_tokens_list = [
                tool_use_id_to_result_tokens.get(tu_id, 0) for tu_id in tool_use_ids
            ]
            if not any(result_tokens_list):
                continue
            per_call = sum(result_tokens_list) // len(result_tokens_list)
            leaked = (len(tool_use_ids) - 1) * per_call
            if leaked <= 0:
                continue
            total += leaked
            findings.append(Finding(
                location=f"tool[{tool_name}].repeat({len(tool_use_ids)})",
                leaked_tokens=leaked,
                confidence="low",
                suggestion=(
                    f"Tool '{tool_name}' called {len(tool_use_ids)} times with identical "
                    f"input. Re-using the prior result instead of re-calling could save "
                    f"{leaked} tok."
                ),
                evidence={
                    "tool_name": tool_name,
                    "repeat_count": len(tool_use_ids),
                    "per_call_result_tokens": per_call,
                },
                evidence_kind="signal",
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 6: Register**

Add `tool_result_repetition` to `tlp/analyzers/__init__.py` imports.

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_analyzers/test_tool_result_repetition.py -v
uv run pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/tool_result_repetition.py tlp/analyzers/__init__.py tlp/config/defaults.yaml tests/fixtures/synthetic/tool_repeat_trace.jsonl tests/test_analyzers/test_tool_result_repetition.py
git commit -m "feat(analyzers): tool_result_repetition (signal) — repeated identical tool call"
```

---

## Task 8: aggregate --include-subagents flag

**Files:**
- Modify: `tlp/aggregate/run.py`
- Modify: `tlp/cli.py`
- Modify: `tests/test_aggregate.py`
- Modify: `tests/test_cli_e2e.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_aggregate.py`:

```python
def test_expand_paths_includes_subagents_when_flag_set(tmp_path):
    from tlp.aggregate.run import expand_paths
    parent = tmp_path / "parent.jsonl"
    parent.write_text("{}\n")
    sub_dir = tmp_path / "abc" / "subagents"
    sub_dir.mkdir(parents=True)
    sub = sub_dir / "agent-1.jsonl"
    sub.write_text("{}\n")
    # Default: excluded
    out_default = expand_paths([tmp_path])
    assert sub not in out_default
    # With flag: included
    out_inc = expand_paths([tmp_path], include_subagents=True)
    assert sub in out_inc
```

Append to `tests/test_cli_e2e.py`:

```python
def test_cli_aggregate_include_subagents_flag(tmp_path):
    """--include-subagents flag passes through to expand_paths."""
    parent = tmp_path / "parent.jsonl"
    # Minimal valid trace
    parent.write_text(
        '{"type":"user","sessionId":"p","uuid":"u","message":{"role":"user","content":"hi"}}\n'
        '{"type":"assistant","sessionId":"p","uuid":"a","message":{"role":"assistant","id":"m","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n'
    )
    r = _run("aggregate", str(tmp_path), "--format", "json", "--include-subagents")
    assert r.returncode == 0
    import json as json_module
    data = json_module.loads(r.stdout)
    assert data["session_count"] == 1
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_aggregate.py tests/test_cli_e2e.py -v
```

Expected: 2 new tests FAIL (kwarg not accepted, flag doesn't exist).

- [ ] **Step 3: Modify `tlp/aggregate/run.py`**

Update `expand_paths`:

```python
def expand_paths(paths: list[Path], *, include_subagents: bool = False) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)
        if p.is_dir():
            for jsonl in sorted(p.rglob("*.jsonl")):
                if "subagents" in jsonl.parts and not include_subagents:
                    continue
                out.append(jsonl)
        elif p.is_file() and p.suffix == ".jsonl":
            out.append(p)
    return out
```

Update `aggregate()` signature to accept and forward `include_subagents`:

```python
def aggregate(
    paths: list[Path],
    *,
    config_path: Path | None = None,
    pricing_path: Path | None = None,
    outlier_multiplier: float | None = None,
    min_confidence: str = "low",
    include_subagents: bool = False,
) -> AggregateReport:
    ...
    files = expand_paths(paths, include_subagents=include_subagents)
    ...
```

- [ ] **Step 4: Modify `tlp/cli.py`**

In the `aggregate` typer command, add the option:

```python
@app.command(name="aggregate")
def aggregate(
    paths: list[Path] = typer.Argument(..., help="One or more .jsonl files or directories"),
    format: str = typer.Option("table", "--format"),
    output: Optional[Path] = typer.Option(None, "--output"),
    config_path: Optional[Path] = typer.Option(None, "--config"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing"),
    outlier_multiplier: Optional[float] = typer.Option(None, "--outlier-multiplier"),
    min_confidence: str = typer.Option("low", "--min-confidence"),
    include_subagents: bool = typer.Option(False, "--include-subagents",
                                            help="Include subagent transcripts (subagents/ dirs)"),
) -> None:
    ...
    report = aggregate_run(
        paths,
        config_path=config_path,
        pricing_path=pricing_path,
        outlier_multiplier=outlier_multiplier,
        min_confidence=min_confidence,
        include_subagents=include_subagents,
    )
    ...
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_aggregate.py tests/test_cli_e2e.py -v
uv run pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add tlp/aggregate/run.py tlp/cli.py tests/test_aggregate.py tests/test_cli_e2e.py
git commit -m "feat(aggregate): --include-subagents flag"
```

---

## Task 9: e2e analyzer count update + version + README

**Files:**
- Modify: `tests/test_cli_e2e.py` (existing analyzer set tests)
- Modify: `tlp/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Update e2e analyzer count assertions**

Use grep to find:
```bash
grep -rn "len(data\[.reports.\]) == 6\|analyzer_names == {" tests/test_cli_e2e.py
```

For each match, update:
- `len(data["reports"]) == 6` → `== 10`
- analyzer name sets: add the 4 new analyzer names:

```python
assert analyzer_names == {
    "stale_context", "redundant_restatement",
    "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
    "cache_turnover_cost",
    "subagent_context_overdump", "system_prompt_audit",
    "roundtrip_inflation", "tool_result_repetition",
}
```

- [ ] **Step 2: Bump version**

`tlp/__init__.py`:
```python
__version__ = "0.5.0"
```

`pyproject.toml`:
```toml
version = "0.5.0"
```

- [ ] **Step 3: README update**

Tagline (first line of README, currently mentions "wasted LLM tokens"):

> Measure actionable LLM token costs in Claude Code sessions.

Update the lever catalog section (replace existing v0.4 table):

```markdown
## Levers (10)

v0.5.0 aligned to the [blog 6-lever taxonomy](https://leejk.vercel.app/notes/2026-05-21-token-frugality): 5/6 covered, 1 deferred (MCP server activation → v0.6).

### Confirmed leak (4) — actionable, direct prescription verified

| name | bucket | what it catches | prescription |
|---|---|---|---|
| format_boilerplate | output | preambles/closers repeated across turns | "no preamble" or stop sequence |
| cache_turnover_cost (recoverable) | cache_creation | TTL idle expiry (gap ≥ 300s) | reduce idle time |
| redundant_restatement | input | near-duplicate text blocks (jaccard ≥ 0.9) | move to system prompt |
| subagent_context_overdump | input | subagent dispatch prompt > 5k tok | narrow scope on next dispatch |

### Signal-only (6) — measurement, prescription unverified

| name | bucket | what it measures |
|---|---|---|
| stale_context | input | blocks unreferenced for N turns |
| verbose_tool_results | input | tool output low citation ratio |
| reasoning_overrun.dup | output | duplicate sentence in thinking |
| reasoning_overrun.ratio | output | high thinking/output ratio |
| cache_turnover_cost (architectural) | cache_creation | per-turn cache invalidation < 300s |
| system_prompt_audit | input | stable system prompt > 15k tok |
| roundtrip_inflation | input | consecutive short user messages |
| tool_result_repetition | input | identical tool calls repeated |
```

(Note: the catalog shows 10 lever entries; reasoning_overrun has two sub-cases counted separately, like cache_turnover_cost. Final count is 10 LeverCategory enum values, of which 4 are confirmed-only and 4 are signal-only; cache_turnover_cost and reasoning_overrun emit both kinds.)

Add a one-line note near the tagline:

> 10 lever scanner. Confirmed leak = actionable; signal = measurement worth inspecting.

- [ ] **Step 4: Run full suite + ruff**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all pass (~125-130 tests with the new ones), ruff clean.

- [ ] **Step 5: Verify version sync**

```bash
uv run python -c "import tlp; print(tlp.__version__)"
grep '^version' pyproject.toml
```

Both `0.5.0`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli_e2e.py tlp/__init__.py pyproject.toml README.md
git commit -m "docs(v0.5.0): bump 0.5.0 + README 10-lever catalog + tagline"
```

---

## Self-Review

**Spec coverage:**

| Spec § | Implemented in |
|---|---|
| §3 Architecture (4 new files, 1 helper extract) | Tasks 3, 4, 5, 6, 7 |
| §4.1 LeverCategory 4 additions | Task 1 |
| §4.2 ParsedTrace.is_subagent | Task 1 + Task 2 (parser) |
| §5.1 subagent_context_overdump | Task 4 |
| §5.2 system_prompt_audit | Task 5 |
| §5.3 roundtrip_inflation | Task 6 |
| §5.4 tool_result_repetition | Task 7 |
| §6 Aggregate include_subagents | Task 8 |
| §7 CLI flag | Task 8 |
| §8 Config 4 new blocks | Tasks 4, 5, 6, 7 (each adds its own block) |
| §11 Testing | Each task ships TDD; ~12 new tests |
| §13 Migration + README | Task 9 |

**Placeholder scan:** No "TBD/TODO" in steps. Generated fixtures use Python helper inline for clarity.

**Type consistency:**
- `LeverCategory` 4 values added in Task 1, referenced in Tasks 4-7 analyzers ✓
- `ParsedTrace.is_subagent` set in Task 2 parser, read in Task 4 (subagent_context_overdump) and Task 5 (system_prompt_audit short-circuit) ✓
- `estimate_stable_prefix` helper signature in Task 3 matches consumer in Task 5 ✓
- `expand_paths(paths, *, include_subagents)` in Task 8 matches CLI usage in Task 8 ✓

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-29-token-leak-profiler-v0.5.md`. User review skipped per session instruction — proceed with subagent-driven execution.
