# Token Leak Profiler v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three concurrent precision changes — (A) Finding.evidence_kind split confirmed/signal, (B) cache_miss_penalty analyzer, (C) tlp schema-dump subcommand + spec-checklist doc.

**Architecture:** Minimal-침습 incremental edit on v1's Registry + ParsedTrace. No new runtime deps. Backward-compat default `evidence_kind="confirmed"` keeps all 53 v1 tests green; v2 adds ~10 tests plus one new analyzer with synthetic fixture.

**Tech Stack:** Python 3.11+, uv, typer (multi-command), rich, datasketch, pyyaml, pytest. Same as v1.

**Spec:** [2026-05-28-token-leak-profiler-v2-design.md](../specs/2026-05-28-token-leak-profiler-v2-design.md)

---

## File Structure

```
token-leak-profiler/
  tlp/
    __init__.py                            # MODIFY: __version__ 0.1.0 → 0.2.0
    types.py                               # MODIFY: Finding.evidence_kind + LeakReport properties
    analyzers/
      stale_context.py                     # MODIFY: explicit evidence_kind="confirmed"
      redundant_restatement.py             # MODIFY: explicit evidence_kind="confirmed"
      tool_schema_bloat.py                 # MODIFY: explicit evidence_kind="confirmed"
      verbose_tool_results.py              # MODIFY: explicit evidence_kind="confirmed"
      format_boilerplate.py                # MODIFY: explicit evidence_kind="confirmed"
      reasoning_overrun.py                 # MODIFY: per-finding evidence_kind branching
      cache_miss_penalty.py                # NEW
    config/
      defaults.yaml                        # MODIFY: cache_miss_penalty thresholds
    reporter/
      json_renderer.py                     # MODIFY: confirmed/signal breakdown
      table.py                             # MODIFY: two-line summary + kind column
    cli.py                                 # MODIFY: schema-dump subcommand, remove _noop
    schema/
      __init__.py                          # NEW
      dump.py                              # NEW
  tests/
    fixtures/synthetic/
      cache_miss_trace.jsonl               # NEW
      visible_thinking_trace.jsonl         # NEW
    test_types.py                          # EXTEND: evidence_kind default + LeakReport props
    test_analyzers/
      test_cache_miss_penalty.py           # NEW
      test_reasoning_overrun.py            # EXTEND: confirmed vs signal branching
    test_reporter.py                       # EXTEND: confirmed/signal breakdown
    test_cli_e2e.py                        # EXTEND: schema-dump subprocess
    test_schema_dump.py                    # NEW
  docs/
    spec-checklist.md                      # NEW
```

---

## Task 1: Finding.evidence_kind + LeakReport breakdown properties

**Files:**
- Modify: `tlp/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write failing test (extend existing test file)**

Append to `tests/test_types.py`:

```python
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
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_types.py -v
```

Expected: FAIL — `Finding` has no `evidence_kind` parameter; `LeakReport` has no `confirmed_tokens` / `signal_tokens` properties.

- [ ] **Step 3: Modify `tlp/types.py`**

Add at the top of the file after `Confidence = Literal[...]`:

```python
EvidenceKind = Literal["confirmed", "signal"]
```

Change the `Finding` dataclass — add `evidence_kind` field with default `"confirmed"`:

```python
@dataclass
class Finding:
    location: str
    leaked_tokens: int
    confidence: Confidence
    suggestion: str
    evidence: dict = field(default_factory=dict)
    evidence_kind: EvidenceKind = "confirmed"
```

Change the `LeakReport` dataclass — add two properties at the bottom of the class:

```python
@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int
    leaked_cost_usd: float
    findings: list[Finding]
    error: str | None = None

    @property
    def confirmed_tokens(self) -> int:
        return sum(f.leaked_tokens for f in self.findings if f.evidence_kind == "confirmed")

    @property
    def signal_tokens(self) -> int:
        return sum(f.leaked_tokens for f in self.findings if f.evidence_kind == "signal")
```

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_types.py -v
```

Expected: 9 passed (6 original + 3 new).

- [ ] **Step 5: Run full suite — make sure v1 tests still pass**

```bash
uv run pytest -q
```

Expected: all 56 passed (53 v1 + 3 new). Backward compat is the key invariant: existing analyzer/reporter code constructs `Finding(...)` without `evidence_kind` and gets the default.

- [ ] **Step 6: Commit**

```bash
git add tlp/types.py tests/test_types.py
git commit -m "feat(types): Finding.evidence_kind + LeakReport breakdown properties"
```

---

## Task 2: Mark all five content-based analyzers as confirmed

This is a mechanical change with no behavioral effect (default is `"confirmed"`). The explicit annotation makes intent self-documenting and protects against future analyzer changes that produce signal-kind findings without realizing it.

**Files:**
- Modify: `tlp/analyzers/stale_context.py`
- Modify: `tlp/analyzers/redundant_restatement.py`
- Modify: `tlp/analyzers/tool_schema_bloat.py`
- Modify: `tlp/analyzers/verbose_tool_results.py`
- Modify: `tlp/analyzers/format_boilerplate.py`

- [ ] **Step 1: Add `evidence_kind="confirmed"` to every `Finding(...)` constructor in these five files**

Use grep to enumerate:

```bash
grep -rn "Finding(" tlp/analyzers/stale_context.py tlp/analyzers/redundant_restatement.py tlp/analyzers/tool_schema_bloat.py tlp/analyzers/verbose_tool_results.py tlp/analyzers/format_boilerplate.py
```

For each `Finding(...)` call in those five files, add `evidence_kind="confirmed"` as the last keyword argument before the closing paren. Example transformation:

Before:
```python
findings.append(Finding(
    location=f"turn[{i}].blocks[{bi}]",
    leaked_tokens=block.tokens,
    confidence="mid",
    suggestion="...",
    evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
))
```

After:
```python
findings.append(Finding(
    location=f"turn[{i}].blocks[{bi}]",
    leaked_tokens=block.tokens,
    confidence="mid",
    suggestion="...",
    evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
    evidence_kind="confirmed",
))
```

Do this for every `Finding(...)` call in:
- `stale_context.py` (1 site)
- `redundant_restatement.py` (1 site)
- `tool_schema_bloat.py` (1 site)
- `verbose_tool_results.py` (1 site)
- `format_boilerplate.py` (2 sites — one prefix, one suffix)

Use grep again to confirm zero remaining `Finding(` calls without `evidence_kind` in these five files (be careful — the analyzer file may have other tokens called `Finding`, but the constructor pattern `Finding(` followed by location is the target).

- [ ] **Step 2: Run full suite**

```bash
uv run pytest -q
```

Expected: 56 passed (same count — no behavior change).

- [ ] **Step 3: Commit**

```bash
git add tlp/analyzers/stale_context.py tlp/analyzers/redundant_restatement.py tlp/analyzers/tool_schema_bloat.py tlp/analyzers/verbose_tool_results.py tlp/analyzers/format_boilerplate.py
git commit -m "refactor(analyzers): mark 5 content-based analyzers as evidence_kind=confirmed"
```

---

## Task 3: reasoning_overrun branches confirmed vs signal

**Files:**
- Modify: `tlp/analyzers/reasoning_overrun.py`
- Create: `tests/fixtures/synthetic/visible_thinking_trace.jsonl`
- Modify: `tests/test_analyzers/test_reasoning_overrun.py`

- [ ] **Step 1: Write fixture for visible-thinking-with-duplicates case**

Create `tests/fixtures/synthetic/visible_thinking_trace.jsonl` (1 line):

```jsonl
{"type":"assistant","sessionId":"s-visible","uuid":"a1","message":{"role":"assistant","id":"msg_visible","content":[{"type":"thinking","thinking":"Let me think carefully about this problem. The user is asking for X. Let me think carefully about this problem. The user is asking for X. I'll proceed."},{"type":"text","text":"Done."}],"usage":{"input_tokens":10,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

The `thinking` field has visible content with a sentence ("Let me think carefully about this problem. The user is asking for X.") appearing twice — the MinHash sentence-similarity path should detect this as a confirmed duplicate.

- [ ] **Step 2: Write failing tests (append to existing test file)**

Append to `tests/test_analyzers/test_reasoning_overrun.py`:

```python
def test_visible_thinking_duplicate_sentence_is_confirmed():
    """When thinking content is visible AND duplicate-sentence detection fires,
    finding is confirmed (real measurement of waste)."""
    fix = Path(__file__).parent.parent / "fixtures" / "synthetic" / "visible_thinking_trace.jsonl"
    trace = parse(fix)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    # At least one finding from the duplicate-sentence path
    confirmed_findings = [f for f in r.findings if f.evidence_kind == "confirmed"]
    assert len(confirmed_findings) >= 1
    assert confirmed_findings[0].confidence == "mid"


def test_redacted_thinking_is_signal_not_confirmed():
    """Extends the existing redacted-thinking test — confirms evidence_kind is signal."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (
                Block("thinking", "", None, None, None, 0),
                Block("text", "Z.", None, None, None, 1),
            ), Usage(input_tokens=10, output_tokens=500, cache_read_tokens=0, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.findings[0].evidence_kind == "signal"
    assert r.findings[0].confidence == "low"
```

The existing `test_redacted_thinking_estimated_from_usage_delta` test stays; the new `test_redacted_thinking_is_signal_not_confirmed` adds the explicit evidence_kind assertion. Confidence on `test_redacted...` already asserts `"low"` (was fixed in commit `e0d0083`).

- [ ] **Step 3: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
```

Expected: existing tests pass; the two new tests FAIL on `f.evidence_kind` AttributeError (Finding has the field but reasoning_overrun never sets `"signal"` yet — actually it might pass since default is "confirmed"; verify which way it fails).

Actually the first new test should FAIL because reasoning_overrun doesn't yet produce confirmed findings from duplicate-sentence path (currently it sets `confidence` based on `dup_tokens > 0` but doesn't set `evidence_kind`). The second new test should FAIL because redacted-thinking findings default to `evidence_kind="confirmed"`.

- [ ] **Step 4: Modify `tlp/analyzers/reasoning_overrun.py`**

Find the `findings.append(Finding(...))` block (currently around line 102-117 based on v1.1) and replace it. The full block, after change:

```python
            total += leak
            # Distinguish *measured* leak (duplicate sentence pairs in visible
            # thinking) from *signal* (high thinking/output ratio with content
            # we can't see). The ratio alone doesn't prove waste — the thinking
            # may have been useful and unobservable.
            if dup_tokens > 0:
                evidence_kind = "confirmed"
                confidence = "mid"
            else:
                evidence_kind = "signal"
                confidence = "low"
            est_note = " (estimated from usage delta, content not visible)" if thinking_redacted else ""
            findings.append(Finding(
                location=f"turn[{ti}]",
                leaked_tokens=leak,
                confidence=confidence,
                suggestion=(
                    f"thinking={thinking_tokens} tok{est_note} vs productive={productive_output} tok "
                    f"(text={text_tokens}, tool_use={tool_use_tokens}), "
                    f"{len(dup_pairs)} duplicate sentence pair(s) — lower max_thinking_tokens"
                ),
                evidence={
                    "thinking_tokens": thinking_tokens,
                    "text_tokens": text_tokens,
                    "tool_use_tokens": tool_use_tokens,
                    "productive_output_tokens": productive_output,
                    "overrun_tokens": overrun,
                    "duplicate_pairs": dup_pairs[:5],
                    "thinking_redacted": thinking_redacted,
                },
                evidence_kind=evidence_kind,
            ))
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
uv run pytest -q
```

Expected: 5 reasoning_overrun tests pass (3 original + 2 new); full suite still green.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/reasoning_overrun.py tests/fixtures/synthetic/visible_thinking_trace.jsonl tests/test_analyzers/test_reasoning_overrun.py
git commit -m "feat(reasoning_overrun): branch confirmed (dup-sentence) vs signal (ratio-only)"
```

---

## Task 4: cache_miss_penalty analyzer + config

**Files:**
- Create: `tlp/analyzers/cache_miss_penalty.py`
- Modify: `tlp/config/defaults.yaml`
- Create: `tests/fixtures/synthetic/cache_miss_trace.jsonl`
- Create: `tests/test_analyzers/test_cache_miss_penalty.py`
- Modify: `tlp/analyzers/__init__.py` (auto-import for registration)

- [ ] **Step 1: Add config defaults**

Edit `tlp/config/defaults.yaml`, add a new top-level key after `format_boilerplate`:

```yaml
cache_miss_penalty:
  min_recreation_turns: 3
  min_avg_creation_tokens: 1000
```

- [ ] **Step 2: Write fixture — pattern positive case**

Create `tests/fixtures/synthetic/cache_miss_trace.jsonl` (6 lines; turn 0 is normal cache-build, turns 1-4 recreate cache repeatedly):

```jsonl
{"type":"user","sessionId":"s-cm","uuid":"u0","message":{"role":"user","content":"start"}}
{"type":"assistant","sessionId":"s-cm","uuid":"a0","message":{"role":"assistant","id":"m0","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":100,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":5000}}}
{"type":"assistant","sessionId":"s-cm","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":2000,"cache_creation_input_tokens":3000}}}
{"type":"assistant","sessionId":"s-cm","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":2000,"cache_creation_input_tokens":3500}}}
{"type":"assistant","sessionId":"s-cm","uuid":"a3","message":{"role":"assistant","id":"m3","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":2000,"cache_creation_input_tokens":2500}}}
{"type":"assistant","sessionId":"s-cm","uuid":"a4","message":{"role":"assistant","id":"m4","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":2000,"cache_creation_input_tokens":4000}}}
```

Turn 0 (a0) is the initial cache build (excluded by the algorithm). Turns 1-4 each have cache_creation > 1000 → 4 affected turns (≥ 3 min), mean = (3000+3500+2500+4000)/4 = 3250 (≥ 1000 min) → pattern confirmed.

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_cache_miss_penalty.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.cache_miss_penalty import CacheMissPenaltyAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "cache_miss_trace.jsonl"


def test_flags_recurring_cache_creation_pattern():
    trace = parse(FIX)
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert f.location == "session"
    assert f.evidence_kind == "confirmed"
    assert f.evidence["affected_turn_count"] == 4
    assert f.evidence["mean_creation_tokens"] == 3250


def test_no_finding_when_cache_creation_only_in_turn_0():
    """Initial cache build alone shouldn't fire — that's normal."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=5000, cache_creation_tokens=0)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=5000, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_when_below_threshold_count():
    """Fewer than min_recreation_turns affected → empty."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=2000)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=4000, cache_creation_tokens=0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_no_finding_when_mean_below_threshold():
    """Enough turns affected but mean cache_creation below threshold → empty."""
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=100, output_tokens=2, cache_read_tokens=0, cache_creation_tokens=5000)),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=500)),
            Turn(2, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=400)),
            Turn(3, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(input_tokens=10, output_tokens=2, cache_read_tokens=2000, cache_creation_tokens=300)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = CacheMissPenaltyAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_cache_miss_penalty.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tlp.analyzers.cache_miss_penalty'`.

- [ ] **Step 5: Add `CACHE_MISS_PENALTY` to `LeverCategory` enum**

Modify `tlp/types.py` — extend the `LeverCategory` enum:

```python
class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    TOOL_SCHEMA_BLOAT = "tool_schema_bloat"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"
    CACHE_MISS_PENALTY = "cache_miss_penalty"   # NEW
```

Verify the v1 `test_lever_category_values` test in `tests/test_types.py` is also updated to include the new value. Locate this test and update:

```python
def test_lever_category_values():
    assert LeverCategory.STALE_CONTEXT.value == "stale_context"
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_miss_penalty",   # NEW
    }
```

- [ ] **Step 6: Write `tlp/analyzers/cache_miss_penalty.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class CacheMissPenaltyAnalyzer(BaseAnalyzer):
    name = "cache_miss_penalty"
    lever = LeverCategory.CACHE_MISS_PENALTY
    usage_bucket = "cache_creation"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("cache_miss_penalty", {})
        min_recreation_turns = int(c.get("min_recreation_turns", 3))
        min_avg_creation_tokens = int(c.get("min_avg_creation_tokens", 1000))

        # Skip turn 0 (initial cache build is unavoidable) and any turn without usage.
        affected: list[tuple[int, int]] = []  # (turn_index, cache_creation_tokens)
        first_assistant_seen = False
        for ti, turn in enumerate(trace.turns):
            if turn.role != "assistant" or turn.usage is None:
                continue
            if not first_assistant_seen:
                first_assistant_seen = True
                continue  # excluded baseline
            if turn.usage.cache_creation_tokens > 0:
                affected.append((ti, turn.usage.cache_creation_tokens))

        if len(affected) < min_recreation_turns:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        total = sum(tok for _, tok in affected)
        mean = total // len(affected)
        if mean < min_avg_creation_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        confidence = "high" if mean >= 5000 else "mid"
        finding = Finding(
            location="session",
            leaked_tokens=total,
            confidence=confidence,
            suggestion=(
                f"{len(affected)} turns recreated cache (avg {mean} tok each). "
                f"Likely cause: dynamic content at context tail. Check for timestamps, "
                f"counters, or session-meta appended after stable system prompt."
            ),
            evidence={
                "affected_turn_count": len(affected),
                "mean_creation_tokens": mean,
                "total_creation_tokens": total,
                "affected_turn_indexes": [ti for ti, _ in affected][:20],
            },
            evidence_kind="confirmed",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=[finding],
        )
```

- [ ] **Step 7: Wire the new analyzer into the registry import**

Modify `tlp/analyzers/__init__.py` — add `cache_miss_penalty` to the imports list:

```python
"""Importing this package auto-registers all built-in analyzers."""
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.analyzers import (  # noqa: F401  (imports trigger registration)
    stale_context,
    redundant_restatement,
    tool_schema_bloat,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
    cache_miss_penalty,   # NEW
)

__all__ = ["BaseAnalyzer", "registry"]
```

- [ ] **Step 8: Run tests to verify pass**

```bash
uv run pytest tests/test_analyzers/test_cache_miss_penalty.py -v
uv run pytest -q
```

Expected: 4 new tests pass; full suite passes (count is now 60 = 56 + 4).

- [ ] **Step 9: Verify all 7 analyzers auto-register**

```bash
uv run python -c "import tlp.analyzers; print(sorted(tlp.analyzers.registry.names()))"
```

Expected output:

```
['cache_miss_penalty', 'format_boilerplate', 'redundant_restatement', 'reasoning_overrun', 'stale_context', 'tool_schema_bloat', 'verbose_tool_results']
```

- [ ] **Step 10: Commit**

```bash
git add tlp/analyzers/cache_miss_penalty.py tlp/analyzers/__init__.py tlp/types.py tlp/config/defaults.yaml tests/test_types.py tests/fixtures/synthetic/cache_miss_trace.jsonl tests/test_analyzers/test_cache_miss_penalty.py
git commit -m "feat(analyzers): cache_miss_penalty — detect repeated cache_creation pattern"
```

---

## Task 5: JSON reporter — confirmed/signal breakdown

**Files:**
- Modify: `tlp/reporter/json_renderer.py`
- Modify: `tests/test_reporter.py`

- [ ] **Step 1: Write failing tests (append to existing test file)**

Append to `tests/test_reporter.py`:

```python
def test_json_includes_confirmed_and_signal_totals():
    from tlp.types import LeakReport, LeverCategory, Finding
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {}, "confirmed")],
        ),
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("turn[5]", 80, "low", "review", {}, "signal")],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={
        "stale_context": "input", "reasoning_overrun": "output"
    })
    data = json.loads(out)
    assert "confirmed_leak_cost_usd" in data
    assert "signal_attention_cost_usd" in data
    assert "effective_leak_cost_usd" in data
    # Confirmed cost is 20 × $3/Mtok = $0.00006
    assert data["confirmed_leak_cost_usd"] == pytest.approx(20 * 3.0 / 1_000_000)
    # Signal cost is 80 × $15/Mtok = $0.0012
    assert data["signal_attention_cost_usd"] == pytest.approx(80 * 15.0 / 1_000_000)


def test_json_per_report_breakdown_fields_present():
    from tlp.types import LeakReport, LeverCategory, Finding
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=100, leaked_cost_usd=0.0,
            findings=[
                Finding("a", 40, "mid", "x", {}, "confirmed"),
                Finding("b", 60, "low", "x", {}, "signal"),
            ],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"reasoning_overrun": "output"})
    data = json.loads(out)
    rpt = data["reports"][0]
    assert rpt["confirmed_tokens"] == 40
    assert rpt["signal_tokens"] == 60
    assert rpt["findings"][0]["evidence_kind"] == "confirmed"
    assert rpt["findings"][1]["evidence_kind"] == "signal"


def test_json_no_longer_emits_total_effective_leak_cost_usd():
    """v1's total_effective_leak_cost_usd is renamed to effective_leak_cost_usd."""
    out = render_json(_trace(), [], bucket_map={})
    data = json.loads(out)
    assert "total_effective_leak_cost_usd" not in data
    assert "effective_leak_cost_usd" in data
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_reporter.py -v
```

Expected: 3 new tests FAIL (missing keys / wrong key name); 3 v1 tests pass.

There is also one existing v1 test (`test_json_includes_session_and_totals`) that asserts the old `total_effective_leak_cost_usd` key via `data["total_cost_usd"] > 0`. Verify that test still passes by reading it; it should because it doesn't reference the renamed key.

Actually the v1 test in test_reporter.py asserted things on `total_cost_usd`, not `total_effective_leak_cost_usd`. The rename only affects what was added in v1.1 fix `db77d0d`. Verify no v1 test depends on the old name (grep for it):

```bash
grep -rn "total_effective_leak_cost_usd" tests/
```

If anything is found, remove that assertion or update it to use the new name `effective_leak_cost_usd`.

- [ ] **Step 3: Modify `tlp/reporter/json_renderer.py`**

Replace the entire `render_json` function with this updated version:

```python
from __future__ import annotations
import json
from dataclasses import asdict
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_json(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
) -> str:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)

    total_cost = (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )

    # Effective input rate blends fresh input + cache_read + cache_creation by token share.
    total_input_like = total_input + total_cache_read + total_cache_creation
    if total_input_like > 0:
        blended_input_rate = (
            trace.pricing.input_per_mtok * total_input
            + trace.pricing.cache_read_per_mtok * total_cache_read
            + trace.pricing.cache_creation_per_mtok * total_cache_creation
        ) / total_input_like
    else:
        blended_input_rate = trace.pricing.input_per_mtok

    rendered_reports = []
    confirmed_total = 0.0
    signal_total = 0.0
    effective_total = 0.0
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        # Per-bucket nominal cost (cache-naive)
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        # Effective cost: blended input rate for input bucket, real rate for others
        if bucket == "input":
            effective_cost = r.leaked_tokens / 1_000_000 * blended_input_rate
        else:
            effective_cost = cost
        effective_total += effective_cost
        # Per-evidence-kind breakdown
        confirmed_tok = r.confirmed_tokens
        signal_tok = r.signal_tokens
        confirmed_cost = trace.pricing.cost(confirmed_tok, bucket)
        signal_cost = trace.pricing.cost(signal_tok, bucket)
        confirmed_total += confirmed_cost
        signal_total += signal_cost
        rendered_reports.append({
            "analyzer": r.analyzer,
            "lever": r.lever.value,
            "usage_bucket": bucket,
            "leaked_tokens": r.leaked_tokens,
            "confirmed_tokens": confirmed_tok,
            "signal_tokens": signal_tok,
            "leaked_cost_usd": cost,
            "effective_cost_usd": effective_cost,
            "findings": [asdict(f) for f in r.findings],
            "error": r.error,
        })

    payload = {
        "session_id": trace.session_id,
        "turn_count": len(trace.turns),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_creation,
        "total_cost_usd": total_cost,
        "confirmed_leak_cost_usd": confirmed_total,
        "signal_attention_cost_usd": signal_total,
        "effective_leak_cost_usd": effective_total,
        "blended_input_rate_per_mtok": blended_input_rate,
        "tokenizer": {"mode": tokenizer_mode, "verify_drift_pct": verify_drift_pct},
        "reports": rendered_reports,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_reporter.py -v
uv run pytest -q
```

Expected: all reporter tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add tlp/reporter/json_renderer.py tests/test_reporter.py
git commit -m "feat(reporter): JSON confirmed/signal breakdown + rename effective field"
```

---

## Task 6: Table reporter — two-line summary + kind column

**Files:**
- Modify: `tlp/reporter/table.py`
- Modify: `tests/test_reporter.py`

- [ ] **Step 1: Write failing test (append)**

Append to `tests/test_reporter.py`:

```python
def test_table_shows_two_separate_summary_lines():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {}, "confirmed")],
        ),
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("turn[5]", 80, "low", "review", {}, "signal")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input", "reasoning_overrun": "output"},
        console=console,
    )
    output = buf.getvalue()
    assert "Confirmed leak:" in output
    assert "Attention signals:" in output
    assert "Effective leak" in output
    # "Estimated total leak" header should be GONE
    assert "Estimated total leak" not in output


def test_table_findings_section_shows_kind_column():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=100, leaked_cost_usd=0.0,
            findings=[
                Finding("turn[1]", 50, "mid", "dup detected", {}, "confirmed"),
                Finding("turn[2]", 50, "low", "ratio high", {}, "signal"),
            ],
        ),
    ]
    render_table(
        _trace(), reports,
        bucket_map={"reasoning_overrun": "output"},
        console=console,
    )
    output = buf.getvalue()
    assert "kind" in output.lower()
    assert "CONF" in output
    assert "SIG" in output
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_reporter.py -v
```

Expected: 2 new tests FAIL (current table doesn't have those strings).

- [ ] **Step 3: Modify `tlp/reporter/table.py`**

Replace the entire `render_table` function with this updated version:

```python
from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich import box
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_table(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    findings_per_lever: int = 5,
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()

    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    total_cost = (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )

    console.rule(f"[bold]Token Leak Profile — session {trace.session_id}")
    console.print(
        f"turns: {len(trace.turns)}  ·  "
        f"input(fresh): {total_input:,}  ·  output: {total_output:,}  ·  "
        f"cost: ${total_cost:.4f}"
    )
    if total_cache_read or total_cache_creation:
        console.print(
            f"[dim]cache_read: {total_cache_read:,}  ·  "
            f"cache_creation: {total_cache_creation:,}[/dim]"
        )
    if verify_drift_pct is not None:
        console.print(f"[dim]tokenizer={tokenizer_mode}, verify drift {verify_drift_pct:+.1f}%[/dim]")

    # Blended input rate
    total_input_like = total_input + total_cache_read + total_cache_creation
    blended_input_rate = (
        (trace.pricing.input_per_mtok * total_input
         + trace.pricing.cache_read_per_mtok * total_cache_read
         + trace.pricing.cache_creation_per_mtok * total_cache_creation) / total_input_like
        if total_input_like > 0 else trace.pricing.input_per_mtok
    )

    # Summary table: two columns (confirmed, signal) replace single tokens
    summary = Table(box=box.SIMPLE_HEAVY, title="Leak by lever")
    summary.add_column("lever", style="cyan")
    summary.add_column("confirmed", justify="right")
    summary.add_column("signal", justify="right")
    summary.add_column("cost ($)", justify="right")
    summary.add_column("% of total", justify="right")
    confirmed_total = 0.0
    signal_total = 0.0
    effective_total = 0.0
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        confirmed_cost = trace.pricing.cost(r.confirmed_tokens, bucket)
        signal_cost = trace.pricing.cost(r.signal_tokens, bucket)
        confirmed_total += confirmed_cost
        signal_total += signal_cost
        if bucket == "input":
            effective_total += r.leaked_tokens / 1_000_000 * blended_input_rate
        else:
            effective_total += cost
        pct = (r.leaked_tokens / max(total_input + total_output, 1)) * 100
        marker = " [red]ERR[/red]" if r.error else ""
        summary.add_row(
            r.lever.value + marker,
            f"{r.confirmed_tokens:,}",
            f"{r.signal_tokens:,}",
            f"{cost:.4f}",
            f"{pct:.1f}%",
        )
    console.print(summary)

    console.print(
        f"[bold]Confirmed leak:[/bold] "
        f"${confirmed_total:.4f} [dim](content-based measurement)[/dim]"
    )
    console.print(
        f"[bold]Attention signals:[/bold] "
        f"${signal_total:.4f} [dim](high thinking-ratio etc., not proven waste)[/dim]"
    )
    console.print(
        f"[bold]Effective leak (cache-adjusted):[/bold] "
        f"~${effective_total:.4f} "
        f"[dim](blended input rate ${blended_input_rate:.2f}/Mtok)[/dim]"
    )

    # Findings per lever — add `kind` column
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        if r.error:
            console.rule(f"[yellow]{r.lever.value} — analyzer error: {r.error}[/yellow]")
            continue
        if not r.findings:
            continue
        console.rule(f"[bold cyan]{r.lever.value}[/bold cyan]")
        ftab = Table(box=box.MINIMAL, show_header=True)
        ftab.add_column("location", style="dim", overflow="fold")
        ftab.add_column("tokens", justify="right")
        ftab.add_column("kind", justify="center")
        ftab.add_column("conf", justify="center")
        ftab.add_column("suggestion", overflow="fold")
        for f in r.findings[:findings_per_lever]:
            kind_label = "CONF" if f.evidence_kind == "confirmed" else "SIG"
            ftab.add_row(f.location, f"{f.leaked_tokens:,}", kind_label, f.confidence, f.suggestion)
        console.print(ftab)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_reporter.py -v
uv run pytest -q
```

Expected: all tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add tlp/reporter/table.py tests/test_reporter.py
git commit -m "feat(reporter): table two-line summary (confirmed vs signal) + kind column"
```

---

## Task 7: schema-dump module

**Files:**
- Create: `tlp/schema/__init__.py`
- Create: `tlp/schema/dump.py`
- Create: `tests/test_schema_dump.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_schema_dump.py`:

```python
from pathlib import Path
import json as json_module
from tlp.schema.dump import dump, render_text, render_json
from tlp.schema.dump import SchemaReport


FIX = Path(__file__).parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"


def test_dump_returns_schema_report():
    r = dump(FIX)
    assert isinstance(r, SchemaReport)
    assert r.session_id == "sess-1"
    assert r.event_count == 3


def test_dump_counts_event_types():
    r = dump(FIX)
    assert r.event_types["user"] == 2
    assert r.event_types["assistant"] == 1


def test_dump_counts_assistant_block_types():
    r = dump(FIX)
    # The minimal trace has 1 assistant text block
    assert r.assistant_block_types.get("text", 0) == 1


def test_dump_message_id_stats():
    r = dump(FIX)
    # The minimal trace's single assistant message has no `id` field set —
    # acceptable to treat unique_message_ids as 0 or count missing-as-blank.
    # Just verify the field exists and is non-negative.
    assert r.unique_message_ids >= 0
    assert r.max_message_id_repeat >= 0


def test_dump_usage_totals():
    r = dump(FIX)
    # Minimal trace assistant turn has input=120, output=6
    assert r.usage_totals["input_tokens"] == 120
    assert r.usage_totals["output_tokens"] == 6


def test_render_text_contains_section_headers():
    r = dump(FIX)
    out = render_text(r)
    assert "Session" in out
    assert "events:" in out
    assert "event types:" in out
    assert "usage totals:" in out


def test_render_json_parses_with_expected_keys():
    r = dump(FIX)
    out = render_json(r)
    data = json_module.loads(out)
    assert "session_id" in data
    assert "event_count" in data
    assert "event_types" in data
    assert "assistant_block_types" in data
    assert "usage_totals" in data
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_schema_dump.py -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'tlp.schema'`.

- [ ] **Step 3: Write `tlp/schema/__init__.py`**

```python
from tlp.schema.dump import dump, render_text, render_json, SchemaReport

__all__ = ["dump", "render_text", "render_json", "SchemaReport"]
```

- [ ] **Step 4: Write `tlp/schema/dump.py`**

```python
"""Schema discovery dump — surfaces transcript structure before parsing into ParsedTrace.

Use this as a spec-time tool: before designing or modifying an analyzer that
makes assumptions about the input shape, run `tlp schema-dump <transcript>`
on real sessions to verify those assumptions.
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SchemaReport:
    session_id: str
    event_count: int
    event_types: dict[str, int] = field(default_factory=dict)
    assistant_block_types: dict[str, int] = field(default_factory=dict)
    user_block_types: dict[str, int] = field(default_factory=dict)
    unique_message_ids: int = 0
    max_message_id_repeat: int = 0
    mean_message_id_repeat: float = 0.0
    thinking_visible_count: int = 0
    thinking_redacted_count: int = 0
    tools_defined: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    skipped_event_types: dict[str, int] = field(default_factory=dict)


def dump(path: Path) -> SchemaReport:
    session_id = ""
    event_count = 0
    event_types: Counter[str] = Counter()
    assistant_blocks: Counter[str] = Counter()
    user_blocks: Counter[str] = Counter()
    message_id_counts: Counter[str] = Counter()
    thinking_visible = 0
    thinking_redacted = 0
    tools_defined: set[str] = set()
    tools_called: set[str] = set()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    skipped: Counter[str] = Counter()
    seen_message_id_for_usage: set[str] = set()

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                skipped["__bad_json__"] += 1
                continue

            ev_type = event.get("type", "?")
            event_types[ev_type] += 1

            if not session_id:
                session_id = event.get("sessionId", "") or session_id

            msg = event.get("message")
            if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
                skipped[ev_type] += 1
                continue

            # Tool definitions
            for td in (event.get("tools") or []) + (msg.get("tools") or []):
                name = td.get("name")
                if name:
                    tools_defined.add(name)

            message_id = msg.get("id", "")
            if message_id:
                message_id_counts[message_id] += 1

            content = msg.get("content", [])
            if isinstance(content, str):
                if ev_type == "user":
                    user_blocks["text"] += 1
                else:
                    assistant_blocks["text"] += 1
            elif isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    ct = c.get("type", "?")
                    if ev_type == "user":
                        user_blocks[ct] += 1
                    else:
                        assistant_blocks[ct] += 1
                        if ct == "thinking":
                            if c.get("thinking"):
                                thinking_visible += 1
                            elif c.get("signature"):
                                thinking_redacted += 1
                            else:
                                thinking_redacted += 1
                        elif ct == "tool_use" and c.get("name"):
                            tools_called.add(c["name"])

            # Sum usage once per message.id to avoid streaming-split double count
            usage = msg.get("usage")
            if ev_type == "assistant" and isinstance(usage, dict) and message_id and message_id not in seen_message_id_for_usage:
                seen_message_id_for_usage.add(message_id)
                for k in usage_totals.keys():
                    val = usage.get(k, 0) or 0
                    try:
                        usage_totals[k] += int(val)
                    except (TypeError, ValueError):
                        pass
            elif ev_type == "assistant" and isinstance(usage, dict) and not message_id:
                # No message.id — assume single-event message, count once
                for k in usage_totals.keys():
                    val = usage.get(k, 0) or 0
                    try:
                        usage_totals[k] += int(val)
                    except (TypeError, ValueError):
                        pass

    if message_id_counts:
        unique_message_ids = len(message_id_counts)
        max_repeat = max(message_id_counts.values())
        mean_repeat = sum(message_id_counts.values()) / unique_message_ids
    else:
        unique_message_ids = 0
        max_repeat = 0
        mean_repeat = 0.0

    return SchemaReport(
        session_id=session_id,
        event_count=event_count,
        event_types=dict(event_types),
        assistant_block_types=dict(assistant_blocks),
        user_block_types=dict(user_blocks),
        unique_message_ids=unique_message_ids,
        max_message_id_repeat=max_repeat,
        mean_message_id_repeat=round(mean_repeat, 2),
        thinking_visible_count=thinking_visible,
        thinking_redacted_count=thinking_redacted,
        tools_defined=sorted(tools_defined),
        tools_called=sorted(tools_called),
        usage_totals=usage_totals,
        skipped_event_types=dict(skipped),
    )


def render_text(r: SchemaReport) -> str:
    lines = [
        f"== Session {r.session_id or '<none>'} ==",
        f"events: {r.event_count}",
        "event types:       " + "  ".join(f"{k}={v}" for k, v in sorted(r.event_types.items(), key=lambda x: -x[1])),
        "assistant blocks:  " + "  ".join(f"{k}={v}" for k, v in sorted(r.assistant_block_types.items(), key=lambda x: -x[1])),
        "user blocks:       " + "  ".join(f"{k}={v}" for k, v in sorted(r.user_block_types.items(), key=lambda x: -x[1])),
        f"message.id:        unique={r.unique_message_ids}  max_repeat={r.max_message_id_repeat}  mean_repeat={r.mean_message_id_repeat}",
        f"thinking blocks:   visible={r.thinking_visible_count}  redacted={r.thinking_redacted_count}",
        f"tools defined:     {r.tools_defined}",
        f"tools called:      {r.tools_called}",
        "usage totals:      " + "  ".join(f"{k}={v:,}" for k, v in r.usage_totals.items()),
    ]
    if r.skipped_event_types:
        skipped_summary = "  ".join(f"{k}({v})" for k, v in sorted(r.skipped_event_types.items(), key=lambda x: -x[1]))
        lines.append(f"skipped events:    {skipped_summary}")
    return "\n".join(lines)


def render_json(r: SchemaReport) -> str:
    from dataclasses import asdict
    return json.dumps(asdict(r), ensure_ascii=False, indent=2)
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_schema_dump.py -v
uv run pytest -q
```

Expected: 7 new tests pass; full suite green.

- [ ] **Step 6: Commit**

```bash
git add tlp/schema/ tests/test_schema_dump.py
git commit -m "feat(schema): tlp.schema.dump module for transcript structure discovery"
```

---

## Task 8: CLI schema-dump subcommand + remove _noop workaround

**Files:**
- Modify: `tlp/cli.py`
- Modify: `tests/test_cli_e2e.py`

- [ ] **Step 1: Write failing tests (append to existing test file)**

Append to `tests/test_cli_e2e.py`:

```python
def test_schema_dump_text_output():
    r = _run("schema-dump", str(FIX))
    assert r.returncode == 0, r.stderr
    assert "Session" in r.stdout
    assert "event types:" in r.stdout
    assert "usage totals:" in r.stdout


def test_schema_dump_json_output():
    r = _run("schema-dump", str(FIX), "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "session_id" in data
    assert "event_types" in data
    assert "assistant_block_types" in data


def test_schema_dump_missing_file_exit_1():
    r = _run("schema-dump", "/nonexistent/path.jsonl")
    assert r.returncode == 1


def test_no_args_shows_help():
    r = _run()
    # typer no-args returns 0 and prints help including both subcommands
    assert "analyze" in r.stdout or "analyze" in r.stderr
    assert "schema-dump" in r.stdout or "schema-dump" in r.stderr
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_cli_e2e.py -v
```

Expected: 4 new tests FAIL (no `schema-dump` command exists yet).

- [ ] **Step 3: Modify `tlp/cli.py`**

The current v1 CLI uses a hidden `_noop` workaround for single-command typer behavior. With two real subcommands, that's no longer needed.

Replace `tlp/cli.py` with:

```python
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.reporter import render_table, render_json
from tlp.schema.dump import dump as schema_dump_run, render_text as schema_render_text, render_json as schema_render_json

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    analyzers: Optional[str] = typer.Option(None, "--analyzers", help="comma-separated subset"),
    verify: bool = typer.Option(False, "--verify", help="verify with anthropic count_tokens"),
    min_confidence: str = typer.Option("mid", "--min-confidence", help="low | mid | high"),
    strict: bool = typer.Option(False, "--strict", help="abort on parse errors"),
) -> None:
    """Analyze a Claude Code transcript for token leaks across 7 levers."""
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("table", "json"):
        typer.echo("error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        pricing = load_pricing(pricing_path)
        trace = parse(path, pricing=pricing, strict=strict)
        config = load_defaults(config_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    selected = registry.all()
    if analyzers:
        wanted = {n.strip() for n in analyzers.split(",")}
        selected = [a for a in selected if a.name in wanted]
        if not selected:
            typer.echo(f"error: no matching analyzers in {analyzers!r}", err=True)
            raise typer.Exit(code=1)

    conf_rank = {"low": 0, "mid": 1, "high": 2}
    min_rank = conf_rank.get(min_confidence, 1)

    reports = []
    bucket_map: dict[str, str] = {}
    for cls in selected:
        bucket_map[cls.name] = cls.usage_bucket
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            from tlp.types import LeakReport
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
                error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        # Recompute leaked_tokens after filter so summary matches displayed findings
        r.leaked_tokens = sum(f.leaked_tokens for f in r.findings)
        reports.append(r)

    drift_pct = None
    if verify:
        from tlp.tokenizer.verify import compute_drift_pct
        sample = [
            {"role": "user", "content": (b.text or "")}
            for t in trace.turns for b in t.blocks
            if t.role == "user" and b.kind == "text"
        ][:20]
        local_total = sum(t.usage.input_tokens for t in trace.turns if t.usage)
        drift_pct = compute_drift_pct(local_total, sample)

    findings_per_lever = config.get("report", {}).get("findings_per_lever", 5)

    if format == "json":
        out = render_json(
            trace, reports, bucket_map=bucket_map,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
        )
        if output:
            output.write_text(out)
        else:
            sys.stdout.write(out + "\n")
    else:
        render_table(
            trace, reports, bucket_map=bucket_map,
            findings_per_lever=findings_per_lever,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
            console=Console(force_terminal=False if not sys.stdout.isatty() else None),
        )


@app.command(name="schema-dump")
def schema_dump(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("text", "--format", help="text | json"),
) -> None:
    """Dump structural schema of a transcript (event types, block types, etc.)."""
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("text", "json"):
        typer.echo("error: --format must be 'text' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        report = schema_dump_run(path)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    if format == "json":
        sys.stdout.write(schema_render_json(report) + "\n")
    else:
        sys.stdout.write(schema_render_text(report) + "\n")


if __name__ == "__main__":
    app()
```

The `_noop` workaround from v1 Task 16 is removed — with two real `@app.command()` registrations, typer automatically routes by subcommand.

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_cli_e2e.py -v
uv run pytest -q
```

Expected: all e2e tests pass; full suite green.

- [ ] **Step 5: Smoke test against current session transcript**

```bash
uv run tlp schema-dump ~/.claude/projects/-home-ljk9121-projects/$(ls -t ~/.claude/projects/-home-ljk9121-projects/*.jsonl 2>/dev/null | head -1 | xargs basename)
```

Expected: terse multi-line output with event types histogram, message.id stats, thinking visibility breakdown, tools, usage totals.

- [ ] **Step 6: Commit**

```bash
git add tlp/cli.py tests/test_cli_e2e.py
git commit -m "feat(cli): tlp schema-dump subcommand + remove v1 _noop workaround"
```

---

## Task 9: spec-checklist doc + version bump

**Files:**
- Create: `docs/spec-checklist.md`
- Modify: `tlp/__init__.py`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/spec-checklist.md`**

```markdown
# Spec Checklist — tlp

A reference checklist for writing or updating specs in this project. Cited from
each spec's §2 Inputs section.

## Before writing data model

1. Run `tlp schema-dump <transcript> --format json` against at least **three
   representative real sessions** from `~/.claude/projects/<slug>/`.
2. Attach the three outputs to the spec's §2 Inputs section.
3. Skim each dump and answer: are there any event types or content block types
   that are not already handled, explicitly skipped, or accounted for in the
   data model? If yes, decide handling before writing model.

## Cache modeling is v1-critical (not v2)

Any analyzer reporting input-bucket tokens must specify in the spec:

- How `cache_read_input_tokens` are treated in cost math.
- How `cache_creation_input_tokens` are treated.
- Whether the analyzer's reported `leaked_tokens` represents fresh-input cost,
  blended-rate cost, or raw tokens that the reporter blends downstream.

Skipping this to "v2" leads to ~10× cost mis-reporting on real cache-heavy
workloads (lesson from v1 dogfooding).

## Test fixture coverage

At minimum these synthetic fixtures must exist before the plan declares done:

- One fixture with multi-event message (streaming split, shared `message.id`
  across consecutive events).
- One fixture with redacted thinking block (empty `thinking` field +
  `signature`).
- One fixture with cache_creation pattern (3+ assistant turns each with
  non-trivial `cache_creation_input_tokens`).

## "Real-transcript sanity" definition

Not just "parser ran without traceback on one real session."

Required for sign-off:

- Every event type observed in the three schema dumps is either parsed or
  explicitly listed under "skipped event types" in the spec.
- Total usage from the analyzer's view reconciles within 5% of the Anthropic
  console's reported cost for at least one session (or, if console access is
  unavailable, within 5% of the sum-by-message.id calculation done by hand).
- The `tlp analyze` output on each of the three sessions is inspected by the
  author for sensibility (no NaN, no negative tokens, no obviously wrong
  cost figure).

## Lever taxonomy hygiene

Every new lever must declare:

- Its `usage_bucket` (one of input, output, cache_read, cache_creation).
- Whether findings are `evidence_kind="confirmed"` (content-based measurement)
  or can include `"signal"` (heuristic-only). If a lever produces both kinds,
  document the branching logic explicitly.
- A worst-case test fixture and a no-finding-expected fixture.

## Open Questions in spec §15

`§15 Open Questions` is the appropriate place to defer decisions that need
real-data calibration. Anything in §15 that touches the data model or
analyzer math should be resolved before plan execution starts.
```

- [ ] **Step 2: Bump version**

Modify `tlp/__init__.py`:

```python
__version__ = "0.2.0"
```

- [ ] **Step 3: Update README — mention schema-dump and the new 7th lever**

Replace the `## Levers` section in `README.md` to include the new lever:

```markdown
## Levers

| name | bucket | what it catches |
|---|---|---|
| stale_context | input | message blocks unreferenced for N turns |
| redundant_restatement | input | near-duplicate text blocks (MinHash 5-gram) |
| tool_schema_bloat | input | tool defs that are never called |
| verbose_tool_results | input | tool output that's mostly never cited |
| reasoning_overrun | output | thinking >> productive + duplicate sentences |
| format_boilerplate | output | preambles/closers repeated across turns |
| cache_miss_penalty | cache_creation | repeated cache invalidation pattern |
```

And add a new section about schema discovery after `## Usage`:

```markdown
## Schema discovery

Before writing or updating a spec that depends on transcript shape, dump real
sessions first:

    uv run tlp schema-dump ~/.claude/projects/<slug>/<session>.jsonl

See `docs/spec-checklist.md` for the full pre-spec workflow.
```

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
```

Expected: all 70 tests pass (53 v1 + ~17 v2; exact count may differ by a few based on append/refactor patterns).

- [ ] **Step 5: Commit**

```bash
git add docs/spec-checklist.md tlp/__init__.py README.md
git commit -m "docs: spec-checklist + bump version to 0.2.0 + update README"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Implemented in |
|---|---|
| §1 v2 Goal A/B/C | Tasks 1-9 collectively |
| §2 Inputs (schema-dump) | Task 7 (module), Task 8 (CLI) |
| §3 Architecture file structure | Tasks 1, 4, 7, 8 create new modules in declared locations |
| §4 Data Model (`evidence_kind`, breakdown properties) | Task 1 |
| §5.1 Five analyzers explicit confirmed | Task 2 |
| §5.2 reasoning_overrun branching | Task 3 |
| §5.3 cache_miss_penalty | Task 4 |
| §6 CLI multi-command + schema-dump | Task 8 |
| §7 Reporter JSON breakdown + table changes | Tasks 5, 6 |
| §8 Config thresholds | Task 4 Step 1 |
| §9 spec-checklist doc | Task 9 |
| §10 Error handling | No new behavior — covered by existing CLI/parser patterns |
| §11 Testing strategy | Every task ships TDD tests; counts match (~10 new) |
| §12 No new deps | Verified — only stdlib + existing pinned packages |
| §13 Migration: version bump to 0.2.0 | Task 9 |
| §14 v3+ backlog | Reference only, not implemented |
| §15 Open questions | Decisions deferred per spec |

**Placeholder scan:** No "TBD/TODO/etc." in any step. Every step has either exact code, exact commands, or both.

**Type consistency:**
- `EvidenceKind = Literal["confirmed", "signal"]` defined in Task 1 step 3, used in Tasks 2, 3, 4 explicit constructor calls and Tasks 5, 6 reporter consumers ✓
- `LeakReport.confirmed_tokens` / `signal_tokens` defined in Task 1, used in Tasks 5, 6 ✓
- `LeverCategory.CACHE_MISS_PENALTY` added in Task 4 Step 5, used in Task 4 Step 6 and Task 4 Step 5 enum test ✓
- `cache_miss_penalty` analyzer registered in `__init__.py` in Task 4 Step 7; required to make Task 4 Step 9 verification produce 7 names ✓
- Schema dump signature `dump(path) -> SchemaReport`, `render_text(r)`, `render_json(r)` defined in Task 7, called in Task 8 ✓
- CLI command names `analyze` and `schema-dump` consistent across Tasks 8, 9 ✓

**Test ordering safety:** Task 1's backward-compat default `evidence_kind="confirmed"` means subsequent task suites can run incrementally without breaking the previous task's tests. ✓

**Spec gap audit:** None found. All requirements have an owning task.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-token-leak-profiler-v2.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance then code quality), fast iteration.
2. **Inline Execution** — execute in this session using executing-plans with batch checkpoints.

Which approach?
