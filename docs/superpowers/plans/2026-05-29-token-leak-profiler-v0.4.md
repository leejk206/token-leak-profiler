# Token Leak Profiler v0.4.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Re-classify existing 9 sub-levers by "measurement → action 1:1" rule. confirmed (3) / signal (5) / removed (1). No new analyzers. Tighten redundant_restatement threshold. Add spec-checklist rule 5.

**Architecture:** Surgical edits across analyzers + types + config + reporter framing. ~7 tasks. No new modules.

**Tech Stack:** Same as v0.3.3.

**Spec:** [2026-05-29-token-leak-profiler-v0.4-design.md](../specs/2026-05-29-token-leak-profiler-v0.4-design.md)

---

## File Structure

```
token-leak-profiler/
  pyproject.toml                                # MODIFY: 0.3.3 → 0.4.0
  README.md                                     # MODIFY: levers table + framing note
  tlp/
    __init__.py                                 # MODIFY: __version__
    types.py                                    # MODIFY: remove TOOL_SCHEMA_BLOAT enum
    analyzers/
      __init__.py                               # MODIFY: remove tool_schema_bloat import
      stale_context.py                          # MODIFY: signal-only
      verbose_tool_results.py                   # MODIFY: signal-only
      reasoning_overrun.py                      # MODIFY: dup path signal-only
      redundant_restatement.py                  # MODIFY (config default change only via yaml)
      cache_turnover_cost.py                    # MODIFY: architectural signal-only
      tool_schema_bloat.py                      # DELETE
    config/
      defaults.yaml                             # MODIFY: remove tool_schema_bloat, jaccard 0.8→0.9
    reporter/
      table.py                                  # MODIFY: framing line + description tweaks
  tests/
    test_analyzers/
      test_stale_context.py                     # MODIFY: signal assertions
      test_verbose_tool_results.py              # MODIFY: signal assertions
      test_reasoning_overrun.py                 # MODIFY: dup path signal assertions
      test_redundant_restatement.py             # VERIFY (0.98 fixture still passes at 0.9)
      test_cache_turnover_cost.py               # MODIFY: architectural signal assertions
      test_tool_schema_bloat.py                 # DELETE
    test_types.py                               # MODIFY: enum set update
    test_cli_e2e.py                             # MODIFY: 6 analyzer expectation (was 7)
    test_reporter.py                            # EXTEND: framing warning test
    fixtures/synthetic/bloat_trace.jsonl        # KEEP (used by other tests indirectly)
  docs/
    spec-checklist.md                           # APPEND: Rule 5
```

---

## Task 1: Remove tool_schema_bloat (lever + analyzer + tests)

**Files:**
- Delete: `tlp/analyzers/tool_schema_bloat.py`
- Delete: `tests/test_analyzers/test_tool_schema_bloat.py`
- Modify: `tlp/analyzers/__init__.py`
- Modify: `tlp/types.py`
- Modify: `tests/test_types.py`
- Modify: `tests/test_cli_e2e.py`

- [ ] **Step 1: Update test_types.py expected enum set**

Find `test_lever_category_values` and remove `"tool_schema_bloat"` from the expected set:

```python
def test_lever_category_values():
    assert LeverCategory.STALE_CONTEXT.value == "stale_context"
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_turnover_cost",
    }
```

(6 values now — was 7.)

- [ ] **Step 2: Update test_cli_e2e.py expected analyzer set**

Find `test_e2e_golden_bloat` and similar tests asserting analyzer names set. Replace any:

```python
analyzer_names == {
    "stale_context", "redundant_restatement", "tool_schema_bloat",
    "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
    "cache_turnover_cost",
}
```

with:

```python
analyzer_names == {
    "stale_context", "redundant_restatement",
    "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
    "cache_turnover_cost",
}
```

Also any assertion `len(data["reports"]) == 7` → `== 6`.

Use grep to find all occurrences:
```bash
grep -rn "tool_schema_bloat\|len(data\[.reports.\]) == 7" tests/
```

- [ ] **Step 3: Run tests to verify they now fail at code level (not assertion)**

```bash
uv run pytest tests/test_types.py -v
uv run pytest tests/test_cli_e2e.py -v
```

Expected: test_lever_category_values FAILS (enum still has TOOL_SCHEMA_BLOAT), other test files may pass since module not gone yet but registry will still register.

- [ ] **Step 4: Delete `tlp/analyzers/tool_schema_bloat.py`**

```bash
rm tlp/analyzers/tool_schema_bloat.py
```

- [ ] **Step 5: Delete `tests/test_analyzers/test_tool_schema_bloat.py`**

```bash
rm tests/test_analyzers/test_tool_schema_bloat.py
```

- [ ] **Step 6: Modify `tlp/analyzers/__init__.py`**

Locate the imports list and remove `tool_schema_bloat`. The result should look like:

```python
"""Importing this package auto-registers all built-in analyzers."""
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.analyzers import (  # noqa: F401  (imports trigger registration)
    stale_context,
    redundant_restatement,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
    cache_turnover_cost,
)

__all__ = ["BaseAnalyzer", "registry"]
```

- [ ] **Step 7: Modify `tlp/types.py` — remove TOOL_SCHEMA_BLOAT**

Find the `LeverCategory` enum and remove the `TOOL_SCHEMA_BLOAT = "tool_schema_bloat"` line. The enum should have 6 values.

- [ ] **Step 8: Run full suite**

```bash
uv run pytest -q
```

Expected: most pass; 6-analyzer registry. Some other tests may still need updates in subsequent tasks.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(v0.4.0): remove tool_schema_bloat (Claude Code incompatible)"
```

---

## Task 2: stale_context → signal-only

**Files:**
- Modify: `tlp/analyzers/stale_context.py`
- Modify: `tests/test_analyzers/test_stale_context.py`

- [ ] **Step 1: Modify analyzer's Finding construction**

Find the `findings.append(Finding(...))` block in `tlp/analyzers/stale_context.py`. Change:

```python
findings.append(Finding(
    location=f"turn[{i}].blocks[{bi}]",
    leaked_tokens=block.tokens,
    confidence="mid",
    suggestion=(
        f"turn[{i}] block last referenced at turn[{last_ref}] "
        f"({trailing} turns ago) — compress or drop"
    ),
    evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
    evidence_kind="confirmed",
))
```

to:

```python
findings.append(Finding(
    location=f"turn[{i}].blocks[{bi}]",
    leaked_tokens=block.tokens,
    confidence="low",
    suggestion=(
        f"turn[{i}] block last referenced at turn[{last_ref}] "
        f"({trailing} turns ago) — candidate for review; "
        f"inspect if still needed before compressing (may be cognitive context, not waste)"
    ),
    evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
    evidence_kind="signal",
))
```

- [ ] **Step 2: Update tests**

Find all assertions on stale_context findings. Replace any:
- `f.confidence == "mid"` → `f.confidence == "low"`
- `f.evidence_kind == "confirmed"` → `f.evidence_kind == "signal"`

Use grep:
```bash
grep -n "confidence\|evidence_kind" tests/test_analyzers/test_stale_context.py
```

For each occurrence, update accordingly. Add a new assertion to one existing test:

```python
def test_initial_block_flagged_stale():
    trace = parse(FIX)
    cfg = load_defaults()
    report = StaleContextAnalyzer().analyze(trace, cfg)
    locations = [f.location for f in report.findings]
    assert any("turn[0]" in loc for loc in locations)
    assert report.leaked_tokens > 0
    # v0.4.0: stale_context is signal-only
    assert all(f.evidence_kind == "signal" for f in report.findings)
    assert all(f.confidence == "low" for f in report.findings)
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_analyzers/test_stale_context.py -v
uv run pytest -q
```

Expected: stale_context tests pass; full suite green.

- [ ] **Step 4: Commit**

```bash
git add tlp/analyzers/stale_context.py tests/test_analyzers/test_stale_context.py
git commit -m "refactor(v0.4.0): stale_context → signal-only (no verified prescription)"
```

---

## Task 3: verbose_tool_results → signal-only

**Files:**
- Modify: `tlp/analyzers/verbose_tool_results.py`
- Modify: `tests/test_analyzers/test_verbose_tool_results.py`

- [ ] **Step 1: Modify analyzer Finding construction**

Find the `findings.append(Finding(...))` block. Change:

```python
findings.append(Finding(
    location=f"turn[{ti}].blocks[{bi}]",
    leaked_tokens=leak,
    confidence="mid",
    suggestion=(
        f"tool result ({b.tokens} tok) cited only {citation_ratio:.0%} in next "
        f"{window} turns — truncate or summarize before sending back"
    ),
    evidence={
        "tool_use_id": b.tool_use_id,
        "citation_ratio": round(citation_ratio, 3),
        "result_tokens": b.tokens,
    },
    evidence_kind="confirmed",
))
```

to:

```python
findings.append(Finding(
    location=f"turn[{ti}].blocks[{bi}]",
    leaked_tokens=leak,
    confidence="low",
    suggestion=(
        f"tool result ({b.tokens} tok) cited only {citation_ratio:.0%} in next "
        f"{window} turns — verify the output was actually unused for "
        f"decision-making before truncating; low citation can mean "
        f"'used for cognitive context but not echoed' rather than 'waste'"
    ),
    evidence={
        "tool_use_id": b.tool_use_id,
        "citation_ratio": round(citation_ratio, 3),
        "result_tokens": b.tokens,
    },
    evidence_kind="signal",
))
```

- [ ] **Step 2: Update tests**

Same pattern as Task 2. Update assertions on `evidence_kind` and `confidence`. Add a single explicit:

```python
def test_flags_verbose_tool_result():
    trace = parse(FIX)
    r = VerboseToolResultsAnalyzer().analyze(trace, load_defaults())
    assert any(f.evidence.get("tool_use_id") == "toolu_1" for f in r.findings)
    assert r.leaked_tokens > 0
    # v0.4.0: signal-only
    assert all(f.evidence_kind == "signal" for f in r.findings)
    assert all(f.confidence == "low" for f in r.findings)
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_analyzers/test_verbose_tool_results.py -v
uv run pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add tlp/analyzers/verbose_tool_results.py tests/test_analyzers/test_verbose_tool_results.py
git commit -m "refactor(v0.4.0): verbose_tool_results → signal-only"
```

---

## Task 4: reasoning_overrun.dup → signal-only (ratio unchanged)

**Files:**
- Modify: `tlp/analyzers/reasoning_overrun.py`
- Modify: `tests/test_analyzers/test_reasoning_overrun.py`

- [ ] **Step 1: Modify analyzer — only the `.dup` Finding path**

Locate the `if dup_tokens > 0:` block (around the `findings.append` site). Currently:

```python
if dup_tokens > 0:
    findings.append(Finding(
        location=f"turn[{ti}].dup",
        leaked_tokens=dup_tokens,
        confidence="mid",
        suggestion=(
            f"{len(dup_pairs)} duplicate sentence pair(s) in visible thinking "
            f"— remove repetition, lower max_thinking_tokens"
        ),
        evidence={
            "duplicate_pairs": dup_pairs[:5],
            "thinking_tokens": thinking_tokens,
        },
        evidence_kind="confirmed",
    ))
```

Change to:

```python
if dup_tokens > 0:
    findings.append(Finding(
        location=f"turn[{ti}].dup",
        leaked_tokens=dup_tokens,
        confidence="low",
        suggestion=(
            f"{len(dup_pairs)} duplicate sentence pair(s) in visible thinking "
            f"— review needed; Claude Code thinking budget control by users "
            f"is not currently verified (see v0.4.0 spec)"
        ),
        evidence={
            "duplicate_pairs": dup_pairs[:5],
            "thinking_tokens": thinking_tokens,
        },
        evidence_kind="signal",
    ))
```

The `.ratio` Finding (further down in the function) stays `evidence_kind="signal"` + `confidence="low"` — already signal.

- [ ] **Step 2: Update tests**

Find `test_visible_thinking_duplicate_sentence_is_confirmed` (which may already exist with that name from earlier cycles). It used to assert `evidence_kind="confirmed"` on the dup finding. Update its assertion to `evidence_kind="signal"` and rename or document.

Find `test_visible_thinking_emits_both_dup_and_ratio_findings` (added in v0.3 T4). It asserts both confirmed and signal exist. Update to assert both are signal:

```python
def test_visible_thinking_emits_both_dup_and_ratio_findings():
    """v0.4.0: dup path is now signal-only (thinking control unverified)."""
    fix = Path(__file__).parent.parent / "fixtures" / "synthetic" / "visible_thinking_split.jsonl"
    trace = parse(fix)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    # All findings are signal-only in v0.4.0
    assert all(f.evidence_kind == "signal" for f in r.findings)
    assert all(f.confidence == "low" for f in r.findings)
    # Both .dup and .ratio variants still exist
    assert any(".dup" in f.location for f in r.findings)
    assert any(".ratio" in f.location for f in r.findings)
```

If `test_visible_thinking_duplicate_sentence_is_confirmed` exists and is now misnamed, rename it to `test_visible_thinking_duplicate_sentence_is_signal` and update its assertion.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
uv run pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add tlp/analyzers/reasoning_overrun.py tests/test_analyzers/test_reasoning_overrun.py
git commit -m "refactor(v0.4.0): reasoning_overrun.dup → signal (thinking control unverified)"
```

---

## Task 5: cache_turnover_cost.architectural → signal-only

**Files:**
- Modify: `tlp/analyzers/cache_turnover_cost.py`
- Modify: `tests/test_analyzers/test_cache_turnover_cost.py`

- [ ] **Step 1: Modify analyzer — architectural Finding path**

The analyzer currently emits up to two Findings per analysis: one for `recoverable` events, one for `architectural`. Find the architectural Finding construction and change:

```python
# (recoverable Finding stays confirmed)

# architectural Finding:
findings.append(Finding(
    location="turn_set.architectural",
    leaked_tokens=arch_total,
    confidence=arch_confidence,   # was likely "mid" or "high"
    suggestion=(
        f"{arch_count} cache turnover event(s) are Claude Code default "
        f"behavior (new user turn → re-cache history)..."
    ),
    evidence={...},
    evidence_kind="confirmed",
))
```

to:

```python
findings.append(Finding(
    location="turn_set.architectural",
    leaked_tokens=arch_total,
    confidence="low",
    suggestion=(
        f"{arch_count} cache turnover event(s) are Claude Code default "
        f"behavior (new user turn → re-cache history). Not directly user-fixable "
        f"— signal-only measurement, included for awareness"
    ),
    evidence={...},
    evidence_kind="signal",
))
```

The `recoverable` Finding (above this) stays `evidence_kind="confirmed"`. Verify by reading.

- [ ] **Step 2: Update tests**

Find tests asserting `architectural` Finding's `evidence_kind` or `confidence`. Update to `signal` / `low`.

Add assertion to an existing test exercising both kinds:

```python
def test_recoverable_and_architectural_emit_distinct_findings(...):
    # ... existing setup ...
    findings = report.findings
    rec = [f for f in findings if "recoverable" in f.location]
    arch = [f for f in findings if "architectural" in f.location]
    assert all(f.evidence_kind == "confirmed" for f in rec)
    assert all(f.evidence_kind == "signal" for f in arch)   # v0.4.0
    assert all(f.confidence == "low" for f in arch)         # v0.4.0
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_analyzers/test_cache_turnover_cost.py -v
uv run pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add tlp/analyzers/cache_turnover_cost.py tests/test_analyzers/test_cache_turnover_cost.py
git commit -m "refactor(v0.4.0): cache_turnover.architectural → signal-only (already not user-fixable)"
```

---

## Task 6: redundant_restatement threshold + config + reporter framing

**Files:**
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/reporter/table.py`
- Modify: `tests/test_reporter.py`

- [ ] **Step 1: Update `tlp/config/defaults.yaml`**

Remove the `tool_schema_bloat:` block entirely. Change `redundant_restatement.jaccard_threshold` from 0.8 to 0.9:

Before:
```yaml
redundant_restatement:
  jaccard_threshold: 0.8
  ngram: 5
  num_perm: 256
tool_schema_bloat: {}
```

After:
```yaml
redundant_restatement:
  jaccard_threshold: 0.9
  ngram: 5
  num_perm: 256
```

(`tool_schema_bloat:` block fully deleted.)

- [ ] **Step 2: Verify existing redundant_restatement fixture still detects**

```bash
uv run pytest tests/test_analyzers/test_redundant_restatement.py -v
```

The existing fixture uses near-identical text (jaccard ~0.98), so 0.9 threshold should still fire. If any test fails because the new threshold misses a borderline case, that's expected — adjust the test fixture to be more clearly duplicate.

- [ ] **Step 3: Modify `tlp/reporter/table.py` — add framing line + tweak descriptions**

Find the summary block. Before the `Confirmed leak:` line, add a dim framing note:

```python
    console.print(
        "[dim]Confirmed = actionable. Signals = measurements without "
        "verified prescriptions; inspect before acting.[/dim]"
    )
    console.print(
        f"[bold]Confirmed leak:[/bold] "
        f"${confirmed_total:.4f} [dim](actionable — direct prescription verified)[/dim]"
    )
    console.print(
        f"[bold]Attention signals:[/bold] "
        f"${signal_total:.4f} [dim](measurements without verified prescriptions — "
        f"inspect before acting)[/dim]"
    )
```

Existing "Effective leak (cache-adjusted):" line stays.

- [ ] **Step 4: Add test for framing**

Append to `tests/test_reporter.py`:

```python
def test_table_includes_v0_4_framing_line():
    """v0.4.0: table output explicitly distinguishes actionable from signal."""
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "low", "review", {}, "signal")],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input"},
        console=console,
    )
    output = buf.getvalue()
    assert "actionable" in output.lower()
    assert "inspect before acting" in output.lower()
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_reporter.py -v
uv run pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add tlp/config/defaults.yaml tlp/reporter/table.py tests/test_reporter.py
git commit -m "refactor(v0.4.0): jaccard 0.8→0.9 + reporter framing for actionable vs signals"
```

---

## Task 7: spec-checklist Rule 5 + version + README

**Files:**
- Modify: `docs/spec-checklist.md`
- Modify: `tlp/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Append Rule 5 to `docs/spec-checklist.md`**

Append at end of file:

```markdown
## Rule 5: Measurement → action 1:1 (added v0.4.0)

새 메트릭을 추가하거나 기존 메트릭의 카테고리를 정할 때, 다음 문장이 spec에 명시되어야 한다:

> "이 메트릭이 X 값을 보이면 사용자는 Y 행동을 취해서 그것을 줄일 수 있다."

Y가 일반적으로 가능하지 않으면 (예: Anthropic API 메커니즘이라 사용자 통제 밖, Claude Code 내부 동작, 의도 추론 필요), 해당 메트릭은 **confirmed leak으로 분류 금지** — `evidence_kind="signal"`, `confidence="low"`로 signal-only 출력.

이 룰은 lever 추가 시 + 기존 lever 재평가 시 모두 적용. 룰 자기-적용 일관성 검증을 위한 PR-time 자동 체크는 v0.4.1 backlog.

**과거 사례:**
- v0.2 cache_miss_penalty: 정상 conversation extension 누수 분류 → 룰 5 위반 → v0.3.2/3.3 fix
- v0.3 stale_context: "참조 안 됨 = 안 필요" 가정 → 룰 5 위반 → v0.4.0 signal-only 격하
- v0.3 verbose_tool_results: "인용 안 됨 = 안 필요" 가정 → 룰 5 위반 → v0.4.0 signal-only 격하
- v0.3 reasoning_overrun.dup: thinking 통제권 미확인 → 룰 5 위반 → v0.4.0 signal-only 격하
```

- [ ] **Step 2: Version bump**

Edit `tlp/__init__.py`:

```python
__version__ = "0.4.0"
```

Edit `pyproject.toml`:

```toml
version = "0.4.0"
```

- [ ] **Step 3: README update**

Find the `## Levers` section. Replace with:

```markdown
## Levers

v0.4.0 distinguishes **confirmed leak** (actionable, direct prescription verified) from **signal** (measurement without verified prescription — inspect before acting).

### Confirmed leak (3)

| name | bucket | what it catches | prescription |
|---|---|---|---|
| format_boilerplate | output | preambles/closers repeated across turns | "no preamble" in system prompt or stop sequence |
| cache_turnover_cost (recoverable) | cache_creation | TTL idle expiry (gap ≥ 300s) | reduce idle time |
| redundant_restatement | input | near-duplicate text blocks (MinHash 5-gram, jaccard ≥ 0.9) | move to system prompt |

### Signal-only (5) — measurement, prescription unverified

| name | bucket | what it measures | why signal not confirmed |
|---|---|---|---|
| stale_context | input | blocks unreferenced for N turns | "unreferenced" ≠ "unnecessary" — may be cognitive context |
| verbose_tool_results | input | tool output low citation ratio | "uncited" ≠ "unnecessary" — used for decision-making not echoed |
| reasoning_overrun.dup | output | duplicate sentence in thinking | Claude Code thinking control verifiable? unclear |
| reasoning_overrun.ratio | output | high thinking/output ratio | content not visible (redacted) |
| cache_turnover_cost (architectural) | cache_creation | per-turn cache invalidation < 300s | Claude Code default behavior, not user-fixable |

(`tool_schema_bloat` removed in v0.4.0 — Claude Code transcripts have no raw tool definitions; algorithm structurally inapplicable.)
```

Also add a description line near the top (after the existing tagline):

> Confirmed leak은 처방 검증된 누수입니다. Signals는 측정값이며 사용자가 검토 후 판단합니다.

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all tests pass, ruff clean.

- [ ] **Step 5: Verify version sync**

```bash
uv run python -c "import tlp; print(tlp.__version__)"
grep '^version' pyproject.toml
```

Both must print `0.4.0`.

- [ ] **Step 6: Commit**

```bash
git add docs/spec-checklist.md tlp/__init__.py pyproject.toml README.md
git commit -m "docs(v0.4.0): spec-checklist rule 5 + bump 0.4.0 + README confirmed/signal split"
```

---

## Self-Review

**Spec coverage:**

| Spec § | Implemented in |
|---|---|
| §3 Lever reclassification | Tasks 1 (remove tool_schema_bloat) + 2-5 (signal demotion) |
| §4 Code changes | Tasks 1-6 |
| §4.4 Reporter framing | Task 6 |
| §5 Test changes | Each task ships test updates |
| §6 Config | Task 6 (yaml edits) |
| §7 Rule 5 in spec-checklist | Task 7 |
| §8 Migration / versioning | Task 7 |
| §10 Testing strategy | All tasks include TDD-style updates |

**Placeholder scan:** No "TBD/TODO" in any step. Every step has exact code or commands.

**Type consistency:**
- `evidence_kind="signal"` and `confidence="low"` used consistently across Tasks 2, 3, 4, 5
- `LeverCategory` enum removal (Task 1) → registry update (Task 1 step 6) → test set update (Task 1 step 1) all align on 6 lever values
- Reporter framing text strings (Task 6) match the test assertion strings (Task 6 step 4)

**Spec-checklist self-apply:** This plan applies Rule 5 retroactively to 4 existing levers (stale_context, verbose_tool_results, reasoning_overrun.dup, cache_turnover.architectural). v0.4.0 spec §1 acknowledges this is the gap that v0.3.3 left when applying user-recoverability rule to cache_turnover only.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-29-token-leak-profiler-v0.4.md`.

Execution: subagent-driven (autonomous, no user review gate per session instruction).
