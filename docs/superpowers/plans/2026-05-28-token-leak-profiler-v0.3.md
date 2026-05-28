# Token Leak Profiler v0.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-session `tlp aggregate` + two dogfood-discovered parser fixes (`tools_changed` event absorption, `ai-title` label extraction) + `reasoning_overrun` finding split (confirmed/signal per-evidence-kind, fixes v0.2 final-review concern).

**Architecture:** v0.2's Registry + ParsedTrace stays. New module `tlp/aggregate/` runs the full analyzer set against every session in a path list and emits a per-session table with median-based outlier flagging. Two small parser edits absorb `tools_changed` (real assistant messages currently skipped) and extract `ai-title` (human-readable session labels). reasoning_overrun emits up to two Findings per affected turn so total counts are honest.

**Tech Stack:** Python 3.11+, uv, typer, rich, datasketch, pyyaml, stdlib `statistics`. No new third-party deps.

**Spec:** [2026-05-28-token-leak-profiler-v0.3-design.md](../specs/2026-05-28-token-leak-profiler-v0.3-design.md)

---

## File Structure

```
token-leak-profiler/
  pyproject.toml                          # MODIFY: 0.2.0 → 0.3.0
  README.md                               # MODIFY: aggregate usage + v0.3 levers note
  tlp/
    __init__.py                           # MODIFY: __version__ 0.2.0 → 0.3.0
    types.py                              # MODIFY: ParsedTrace.label optional field
    parser/
      claude_code.py                      # MODIFY: ai-title extract, tools_changed normalize
    analyzers/
      reasoning_overrun.py                # MODIFY: split into .dup + .ratio findings
    aggregate/                            # NEW
      __init__.py
      types.py                            # NEW: SessionRow, AggregateReport
      run.py                              # NEW: expand_paths, aggregate()
      reporter.py                         # NEW: render_table, render_json
    cli.py                                # MODIFY: aggregate subcommand
    config/
      defaults.yaml                       # MODIFY: aggregate.outlier_multiplier
  tests/
    fixtures/synthetic/
      ai_title_trace.jsonl                # NEW
      tools_changed_trace.jsonl           # NEW
      visible_thinking_split.jsonl        # NEW
      aggregate/
        session_normal.jsonl              # NEW
        session_outlier.jsonl             # NEW
    test_parser.py                        # EXTEND: ai-title + tools_changed
    test_analyzers/
      test_reasoning_overrun.py           # EXTEND/REVISE: split semantics
    test_aggregate.py                     # NEW
    test_cli_e2e.py                       # EXTEND: aggregate subprocess
  docs/superpowers/
    specs/2026-05-28-token-leak-profiler-v0.3-design.md
    plans/2026-05-28-token-leak-profiler-v0.3.md
```

Boundary rules:
- `tlp/aggregate/` does NOT depend on `tlp/cli.py` — it is library-callable.
- `tlp/aggregate/reporter.py` is separate from `tlp/reporter/` because the input dataclass differs (AggregateReport vs LeakReport list).
- Parser edits are surgical — no rewrite, additions only.

---

## Task 1: ParsedTrace.label field

**Files:**
- Modify: `tlp/types.py`
- Modify: `tests/test_types.py`

- [ ] **Step 1: Write failing tests (append)**

Append to `tests/test_types.py`:

```python
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
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_types.py -v
```

Expected: 2 new tests FAIL with `TypeError: __init__() got an unexpected keyword argument 'label'`.

- [ ] **Step 3: Modify `tlp/types.py`**

Find the `ParsedTrace` dataclass and add the `label` field as the last field:

```python
@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable
    label: str | None = None
```

The default `None` keeps every existing constructor call backward-compatible.

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
```

Expected: 82 passed (80 v0.2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tlp/types.py tests/test_types.py
git commit -m "feat(types): ParsedTrace.label optional field for session title"
```

---

## Task 2: Parser ai-title extraction

**Files:**
- Modify: `tlp/parser/claude_code.py`
- Create: `tests/fixtures/synthetic/ai_title_trace.jsonl`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write fixture**

Create `tests/fixtures/synthetic/ai_title_trace.jsonl` (3 lines):

```jsonl
{"type":"ai-title","sessionId":"s-title","uuid":"t1","message":{"role":"user","content":"My Custom Session Title"}}
{"type":"user","sessionId":"s-title","uuid":"u1","message":{"role":"user","content":"hi"}}
{"type":"assistant","sessionId":"s-title","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 2: Write failing tests (append)**

Append to `tests/test_parser.py`:

```python
def test_parse_extracts_ai_title_label():
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "ai_title_trace.jsonl"
    t = parse(fix)
    assert t.label == "My Custom Session Title"


def test_parse_label_none_when_no_ai_title():
    """The minimal fixture has no ai-title event."""
    t = parse(FIX)  # FIX is the existing minimal_trace.jsonl path constant
    assert t.label is None
```

- [ ] **Step 3: Run tests to verify fail**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: 2 new tests FAIL (`label` attribute exists from Task 1 but is None; the first test fails because parser doesn't populate it yet).

- [ ] **Step 4: Modify `tlp/parser/claude_code.py`**

Find the first-pass loop where events are collected (just after `for raw_line, line_no in _iter_lines(path):`). Initialize an `ai_title` variable BEFORE the loop:

```python
def parse(path: Path, *, pricing: PricingTable | None = None, strict: bool = False) -> ParsedTrace:
    pricing = pricing or load_pricing()
    session_id = ""
    turns: list[Turn] = []
    tool_defs: dict[str, ToolDef] = {}
    warnings: list[str] = []
    next_index = 0
    ai_title: str | None = None   # NEW

    events: list[tuple[int, str, dict]] = []
    for raw_line, line_no in _iter_lines(path):
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as e:
            ...
```

Then INSIDE the loop, after `event = json.loads(raw_line)` succeeds and BEFORE the `ev_type not in ("user", "assistant")` guard, add ai-title handling. The block should sit right after the `session_id` capture:

```python
        if not session_id:
            session_id = event.get("sessionId", "") or session_id

        ev_type = event.get("type")
        msg = event.get("message")

        # ai-title: extract first non-empty title text, then continue (skip)
        if ev_type == "ai-title" and ai_title is None:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    ai_title = content.strip()
            continue
```

Finally, in the `return ParsedTrace(...)` statement, pass `label=ai_title`:

```python
    return ParsedTrace(
        session_id=session_id,
        turns=tuple(turns),
        tool_defs=dict(tool_defs),
        pricing=pricing,
        label=ai_title,
    )
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_parser.py -v
uv run pytest -q
```

Expected: parser tests pass; full suite 84 passed (82 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add tlp/parser/claude_code.py tests/fixtures/synthetic/ai_title_trace.jsonl tests/test_parser.py
git commit -m "feat(parser): extract ai-title event into ParsedTrace.label"
```

---

## Task 3: Parser tools_changed absorption

**Files:**
- Modify: `tlp/parser/claude_code.py`
- Create: `tests/fixtures/synthetic/tools_changed_trace.jsonl`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write fixture**

Create `tests/fixtures/synthetic/tools_changed_trace.jsonl` (3 lines):

```jsonl
{"type":"assistant","sessionId":"s-tc","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"first message"}],"usage":{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"tools_changed","sessionId":"s-tc","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"thinking","thinking":"","signature":"sig"}],"usage":{"input_tokens":20,"output_tokens":100,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","sessionId":"s-tc","uuid":"a3","message":{"role":"assistant","id":"m3","content":[{"type":"text","text":"third message"}],"usage":{"input_tokens":30,"output_tokens":7,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

Three distinct `message.id`s, three different usage values. After absorption, total output should be 5 + 100 + 7 = 112.

- [ ] **Step 2: Write failing tests (append)**

Append to `tests/test_parser.py`:

```python
def test_parse_absorbs_tools_changed_as_assistant():
    """tools_changed events carry real assistant messages with their own usage."""
    fix = Path(__file__).parent / "fixtures" / "synthetic" / "tools_changed_trace.jsonl"
    t = parse(fix)
    # Three assistant turns
    assistant_turns = [tr for tr in t.turns if tr.role == "assistant"]
    assert len(assistant_turns) == 3
    # Total output: 5 + 100 + 7 = 112 (was 12 in v0.2 because tools_changed was skipped)
    total_output = sum(tr.usage.output_tokens for tr in assistant_turns if tr.usage)
    assert total_output == 112
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_parser.py::test_parse_absorbs_tools_changed_as_assistant -v
```

Expected: FAIL — currently `tools_changed` is skipped, so `total_output` would be 12.

- [ ] **Step 4: Modify `tlp/parser/claude_code.py`**

Find the line:
```python
        ev_type = event.get("type")
```

After it (and before the existing `if ev_type not in ("user", "assistant")` check), insert a normalization:

```python
        ev_type = event.get("type")
        # tools_changed events are real assistant messages with usage; normalize
        # so they flow through the same pipeline. Global message.id dedup
        # (later in second pass) prevents double-counting if any tools_changed
        # shares an id with a prior assistant event.
        if ev_type == "tools_changed":
            ev_type = "assistant"
```

The existing `if ev_type not in ("user", "assistant") or not isinstance(msg, dict):` filter now accepts the normalized type.

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_parser.py -v
uv run pytest -q
```

Expected: full suite 85 passed (84 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add tlp/parser/claude_code.py tests/fixtures/synthetic/tools_changed_trace.jsonl tests/test_parser.py
git commit -m "feat(parser): absorb tools_changed event as assistant message"
```

---

## Task 4: reasoning_overrun finding split

**Files:**
- Modify: `tlp/analyzers/reasoning_overrun.py`
- Create: `tests/fixtures/synthetic/visible_thinking_split.jsonl`
- Modify: `tests/test_analyzers/test_reasoning_overrun.py`

- [ ] **Step 1: Write fixture**

Create `tests/fixtures/synthetic/visible_thinking_split.jsonl` (1 line). Visible thinking with both a duplicate sentence pair AND high overrun ratio (very small productive output):

```jsonl
{"type":"assistant","sessionId":"s-split","uuid":"a1","message":{"role":"assistant","id":"msg_split","content":[{"type":"thinking","thinking":"The user wants something specific here. Let me consider the options carefully. The user wants something specific here. I should respond with a one-word answer based on the analysis. The user wants something specific here."},{"type":"text","text":"OK."}],"usage":{"input_tokens":10,"output_tokens":80,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

The repeated sentence triggers dup_tokens > 0. Productive output is tiny (`"OK." → ~1 token`), so overrun also fires.

- [ ] **Step 2: Write/revise failing tests**

In `tests/test_analyzers/test_reasoning_overrun.py`, the existing `test_visible_thinking_duplicate_sentence_is_confirmed` already asserts at least one confirmed finding — that stays correct. Add a new test that asserts BOTH kinds appear:

Append:

```python
def test_visible_thinking_emits_both_dup_and_ratio_findings():
    """When both duplicate-sentence detection AND overrun fire, we emit two
    distinct Findings (one confirmed, one signal) instead of lumping them."""
    fix = Path(__file__).parent.parent / "fixtures" / "synthetic" / "visible_thinking_split.jsonl"
    trace = parse(fix)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    # At least one confirmed (.dup) and one signal (.ratio) finding for the same turn
    confirmed = [f for f in r.findings if f.evidence_kind == "confirmed"]
    signal = [f for f in r.findings if f.evidence_kind == "signal"]
    assert len(confirmed) >= 1, f"no confirmed findings; got {r.findings}"
    assert len(signal) >= 1, f"no signal findings; got {r.findings}"
    # Locations should be distinct (.dup vs .ratio suffix)
    assert any(".dup" in f.location for f in confirmed)
    assert any(".ratio" in f.location for f in signal)


def test_redacted_thinking_emits_only_ratio_finding():
    """Redacted thinking has no visible content → no duplicate detection.
    Only the ratio path fires → exactly one signal finding."""
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
    assert len(r.findings) == 1
    assert r.findings[0].evidence_kind == "signal"
    assert ".ratio" in r.findings[0].location
```

The existing v0.2 test `test_redacted_thinking_is_signal_not_confirmed` may need an update if it asserted `findings[0].location == f"turn[0]"`. Locate it and change any location assertion to use `".ratio"` substring or remove the bare location check.

- [ ] **Step 3: Run tests to verify fail**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
```

Expected: existing tests may FAIL (location format change) and new tests FAIL.

- [ ] **Step 4: Modify `tlp/analyzers/reasoning_overrun.py`**

Find the existing block that creates one Finding (around line 100-134 in v0.2). Replace the `if dup_tokens > 0: ... else: ...` block plus the single `findings.append(Finding(...))` with two separate appends:

```python
            # Emit confirmed Finding for measured duplicate-sentence content
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

            # Emit signal Finding for ratio-only overrun (cannot prove waste —
            # the thinking content may have been useful and unobservable)
            if overrun > 0:
                est_note = " (estimated from usage delta, content not visible)" if thinking_redacted else ""
                findings.append(Finding(
                    location=f"turn[{ti}].ratio",
                    leaked_tokens=overrun,
                    confidence="low",
                    suggestion=(
                        f"thinking={thinking_tokens} tok{est_note} vs productive={productive_output} "
                        f"(ratio {thinking_tokens/max(productive_output,1):.1f}×) — review necessary"
                    ),
                    evidence={
                        "thinking_tokens": thinking_tokens,
                        "text_tokens": text_tokens,
                        "tool_use_tokens": tool_use_tokens,
                        "productive_output_tokens": productive_output,
                        "overrun_tokens": overrun,
                        "thinking_redacted": thinking_redacted,
                    },
                    evidence_kind="signal",
                ))
```

The `total += leak` and `if leak <= 0: continue` lines stay above; they gate whether either Finding is worth emitting. (If `leak = 0` both `dup_tokens` and `overrun` are 0 and neither inner `if` fires anyway, so the early-continue is still cheap-correct.)

Remove any leftover single-Finding code from the v0.2 block.

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
uv run pytest -q
```

Expected: reasoning_overrun tests pass; full suite green.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/reasoning_overrun.py tests/fixtures/synthetic/visible_thinking_split.jsonl tests/test_analyzers/test_reasoning_overrun.py
git commit -m "feat(reasoning_overrun): split into .dup confirmed + .ratio signal findings"
```

---

## Task 5: Aggregate types

**Files:**
- Create: `tlp/aggregate/__init__.py`
- Create: `tlp/aggregate/types.py`
- Create: `tests/test_aggregate.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_aggregate.py`:

```python
from pathlib import Path
from tlp.aggregate.types import SessionRow, AggregateReport


def test_session_row_construction():
    row = SessionRow(
        session_id="s1",
        label="my session",
        path=Path("/tmp/s1.jsonl"),
        turn_count=10,
        total_cost_usd=1.0,
        effective_leak_cost_usd=0.1,
        leak_ratio=0.1,
        dominant_lever="stale_context",
        is_outlier=False,
    )
    assert row.session_id == "s1"
    assert row.is_outlier is False


def test_aggregate_report_construction():
    rep = AggregateReport(
        sessions=(),
        total_cost_usd=0.0,
        total_effective_leak_usd=0.0,
        median_leak_ratio=0.0,
        outlier_threshold=0.0,
        session_count=0,
    )
    assert rep.session_count == 0
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_aggregate.py -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'tlp.aggregate'`.

- [ ] **Step 3: Write `tlp/aggregate/__init__.py`**

```python
from tlp.aggregate.types import SessionRow, AggregateReport

__all__ = ["SessionRow", "AggregateReport"]
```

- [ ] **Step 4: Write `tlp/aggregate/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    label: str
    path: Path
    turn_count: int
    total_cost_usd: float
    effective_leak_cost_usd: float
    leak_ratio: float
    dominant_lever: str | None
    is_outlier: bool


@dataclass(frozen=True)
class AggregateReport:
    sessions: tuple[SessionRow, ...]
    total_cost_usd: float
    total_effective_leak_usd: float
    median_leak_ratio: float
    outlier_threshold: float
    session_count: int
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_aggregate.py -v
uv run pytest -q
```

Expected: 2 new tests pass; full suite green.

- [ ] **Step 6: Commit**

```bash
git add tlp/aggregate/ tests/test_aggregate.py
git commit -m "feat(aggregate): SessionRow + AggregateReport dataclasses"
```

---

## Task 6: Aggregate run.py (expand_paths + aggregate())

**Files:**
- Create: `tlp/aggregate/run.py`
- Modify: `tlp/aggregate/__init__.py` (re-export)
- Modify: `tlp/config/defaults.yaml` (add outlier_multiplier)
- Create: `tests/fixtures/synthetic/aggregate/session_normal.jsonl`
- Create: `tests/fixtures/synthetic/aggregate/session_outlier.jsonl`
- Modify: `tests/test_aggregate.py`

- [ ] **Step 1: Add config defaults**

Edit `tlp/config/defaults.yaml`, append a new top-level key:

```yaml
aggregate:
  outlier_multiplier: 2.0
```

- [ ] **Step 2: Write the two fixture sessions**

Create `tests/fixtures/synthetic/aggregate/session_normal.jsonl` (4 lines — small session with low leak):

```jsonl
{"type":"user","sessionId":"agg-normal","uuid":"u1","message":{"role":"user","content":"hi"}}
{"type":"assistant","sessionId":"agg-normal","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"text","text":"hello back."}],"usage":{"input_tokens":100,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"agg-normal","uuid":"u2","message":{"role":"user","content":"another short prompt"}}
{"type":"assistant","sessionId":"agg-normal","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"reply"}],"usage":{"input_tokens":100,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

Create `tests/fixtures/synthetic/aggregate/session_outlier.jsonl` (4 lines — session with reasoning_overrun that should trigger high leak ratio):

```jsonl
{"type":"user","sessionId":"agg-outlier","uuid":"u1","message":{"role":"user","content":"do something tricky"}}
{"type":"assistant","sessionId":"agg-outlier","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"thinking","thinking":"","signature":"sig"},{"type":"text","text":"ok"}],"usage":{"input_tokens":100,"output_tokens":5000,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"agg-outlier","uuid":"u2","message":{"role":"user","content":"again"}}
{"type":"assistant","sessionId":"agg-outlier","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"thinking","thinking":"","signature":"sig"},{"type":"text","text":"ok"}],"usage":{"input_tokens":100,"output_tokens":5000,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

The outlier session has redacted thinking with massive output_tokens vs tiny text — reasoning_overrun.ratio signal will fire heavily.

- [ ] **Step 3: Write failing tests (append)**

Append to `tests/test_aggregate.py`:

```python
import tempfile


def test_expand_paths_single_file():
    from tlp.aggregate.run import expand_paths
    fix = Path("tests/fixtures/synthetic/minimal_trace.jsonl")
    out = expand_paths([fix])
    assert out == [fix]


def test_expand_paths_directory_recursive():
    from tlp.aggregate.run import expand_paths
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    out = expand_paths([fix_dir])
    assert len(out) == 2
    assert all(p.suffix == ".jsonl" for p in out)


def test_expand_paths_missing_raises():
    from tlp.aggregate.run import expand_paths
    import pytest as _pytest
    with _pytest.raises(FileNotFoundError):
        expand_paths([Path("/nonexistent/dir/")])


def test_aggregate_empty_input_returns_empty_report():
    from tlp.aggregate.run import aggregate
    with tempfile.TemporaryDirectory() as td:
        rep = aggregate([Path(td)])
    assert rep.session_count == 0
    assert rep.sessions == ()
    assert rep.median_leak_ratio == 0.0


def test_aggregate_two_sessions_flags_outlier():
    from tlp.aggregate.run import aggregate
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    assert rep.session_count == 2
    # The outlier fixture should be flagged (its leak_ratio is >> median × 2)
    outliers = [s for s in rep.sessions if s.is_outlier]
    assert len(outliers) >= 1
    assert any("outlier" in s.session_id for s in outliers)


def test_aggregate_single_session_no_outlier():
    """Single-session aggregation can't have outliers — median equals self."""
    from tlp.aggregate.run import aggregate
    rep = aggregate([Path("tests/fixtures/synthetic/aggregate/session_normal.jsonl")])
    assert rep.session_count == 1
    assert rep.sessions[0].is_outlier is False
```

- [ ] **Step 4: Run tests to verify fail**

```bash
uv run pytest tests/test_aggregate.py -v
```

Expected: 6 new tests FAIL (module not implemented yet).

- [ ] **Step 5: Write `tlp/aggregate/run.py`**

```python
from __future__ import annotations
import statistics
from pathlib import Path

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.aggregate.types import SessionRow, AggregateReport
from tlp.types import LeakReport


def expand_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)
        if p.is_dir():
            out.extend(sorted(p.rglob("*.jsonl")))
        elif p.is_file() and p.suffix == ".jsonl":
            out.append(p)
    return out


def aggregate(
    paths: list[Path],
    *,
    config_path: Path | None = None,
    pricing_path: Path | None = None,
    outlier_multiplier: float | None = None,
    min_confidence: str = "mid",
) -> AggregateReport:
    config = load_defaults(config_path)
    pricing = load_pricing(pricing_path)
    files = expand_paths(paths)

    multiplier = outlier_multiplier if outlier_multiplier is not None else float(
        config.get("aggregate", {}).get("outlier_multiplier", 2.0)
    )

    rows_unflagged: list[SessionRow] = []
    for f in files:
        trace = parse(f, pricing=pricing)
        reports = _run_analyzers(trace, config, min_confidence)
        bucket_map = {r.analyzer: _bucket_for(r.analyzer) for r in reports}
        total_cost = _total_cost(trace)
        eff_leak = _effective_leak(trace, reports, bucket_map)
        leak_ratio = eff_leak / max(total_cost, 1e-9)
        positive = [r for r in reports if r.leaked_tokens > 0]
        dominant = max(positive, key=lambda r: r.leaked_tokens).analyzer if positive else None
        rows_unflagged.append(SessionRow(
            session_id=trace.session_id,
            label=trace.label or (trace.session_id[:8] if trace.session_id else "<unknown>"),
            path=f,
            turn_count=len(trace.turns),
            total_cost_usd=total_cost,
            effective_leak_cost_usd=eff_leak,
            leak_ratio=leak_ratio,
            dominant_lever=dominant,
            is_outlier=False,
        ))

    if not rows_unflagged:
        return AggregateReport(
            sessions=(), total_cost_usd=0.0, total_effective_leak_usd=0.0,
            median_leak_ratio=0.0, outlier_threshold=0.0, session_count=0,
        )

    median_ratio = statistics.median(r.leak_ratio for r in rows_unflagged)
    threshold = median_ratio * multiplier
    flagged: tuple[SessionRow, ...] = tuple(
        SessionRow(
            session_id=row.session_id, label=row.label, path=row.path,
            turn_count=row.turn_count, total_cost_usd=row.total_cost_usd,
            effective_leak_cost_usd=row.effective_leak_cost_usd,
            leak_ratio=row.leak_ratio, dominant_lever=row.dominant_lever,
            is_outlier=(row.leak_ratio > threshold and len(rows_unflagged) > 1),
        )
        for row in rows_unflagged
    )

    return AggregateReport(
        sessions=flagged,
        total_cost_usd=sum(r.total_cost_usd for r in flagged),
        total_effective_leak_usd=sum(r.effective_leak_cost_usd for r in flagged),
        median_leak_ratio=median_ratio,
        outlier_threshold=threshold,
        session_count=len(flagged),
    )


# --- private helpers ---

def _run_analyzers(trace, config, min_confidence: str) -> list[LeakReport]:
    conf_rank = {"low": 0, "mid": 1, "high": 2}
    min_rank = conf_rank.get(min_confidence, 1)
    reports: list[LeakReport] = []
    for cls in registry.all():
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[], error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        r.leaked_tokens = sum(f.leaked_tokens for f in r.findings)
        reports.append(r)
    return reports


def _bucket_for(analyzer_name: str) -> str:
    cls = registry.get(analyzer_name)
    return cls.usage_bucket


def _total_cost(trace) -> float:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    return (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )


def _effective_leak(trace, reports: list[LeakReport], bucket_map: dict[str, str]) -> float:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    total_input_like = total_input + total_cache_read + total_cache_creation
    if total_input_like > 0:
        blended = (
            trace.pricing.input_per_mtok * total_input
            + trace.pricing.cache_read_per_mtok * total_cache_read
            + trace.pricing.cache_creation_per_mtok * total_cache_creation
        ) / total_input_like
    else:
        blended = trace.pricing.input_per_mtok
    eff = 0.0
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        if bucket == "input":
            eff += r.leaked_tokens / 1_000_000 * blended
        else:
            eff += trace.pricing.cost(r.leaked_tokens, bucket)
    return eff
```

- [ ] **Step 6: Update `tlp/aggregate/__init__.py`**

Add the new exports:

```python
from tlp.aggregate.types import SessionRow, AggregateReport
from tlp.aggregate.run import expand_paths, aggregate

__all__ = ["SessionRow", "AggregateReport", "expand_paths", "aggregate"]
```

- [ ] **Step 7: Run tests to verify pass**

```bash
uv run pytest tests/test_aggregate.py -v
uv run pytest -q
```

Expected: aggregate tests pass; full suite green.

- [ ] **Step 8: Commit**

```bash
git add tlp/aggregate/ tlp/config/defaults.yaml tests/fixtures/synthetic/aggregate/ tests/test_aggregate.py
git commit -m "feat(aggregate): expand_paths + aggregate() with median-based outlier flag"
```

---

## Task 7: Aggregate reporter (table + JSON)

**Files:**
- Create: `tlp/aggregate/reporter.py`
- Modify: `tlp/aggregate/__init__.py` (re-export render funcs)
- Modify: `tests/test_aggregate.py`

- [ ] **Step 1: Write failing tests (append)**

Append to `tests/test_aggregate.py`:

```python
import json as json_module
from io import StringIO
from rich.console import Console


def test_render_table_shows_session_rows_and_summary():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_table
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    render_table(rep, console=console)
    output = buf.getvalue()
    assert "Aggregate" in output
    assert "Total:" in output
    assert "Median session leak" in output
    # At least one session label
    assert "agg-normal" in output or "<unknown>" in output


def test_render_table_marks_outlier_visibly():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_table
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    buf = StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    render_table(rep, console=console)
    output = buf.getvalue()
    assert "OUTLIER" in output


def test_render_json_returns_valid_payload():
    from tlp.aggregate.run import aggregate
    from tlp.aggregate.reporter import render_json
    fix_dir = Path("tests/fixtures/synthetic/aggregate")
    rep = aggregate([fix_dir])
    out = render_json(rep)
    data = json_module.loads(out)
    assert data["session_count"] == 2
    assert "sessions" in data
    assert "total_cost_usd" in data
    assert "median_leak_ratio" in data
    assert "outlier_threshold" in data
    # Each session has expected keys
    assert "leak_ratio" in data["sessions"][0]
    assert "is_outlier" in data["sessions"][0]
    assert "dominant_lever" in data["sessions"][0]
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_aggregate.py -v
```

Expected: 3 new tests FAIL with `ImportError`.

- [ ] **Step 3: Write `tlp/aggregate/reporter.py`**

```python
from __future__ import annotations
import json as _json
from dataclasses import asdict
from rich.console import Console
from rich.table import Table
from rich import box

from tlp.aggregate.types import AggregateReport


def render_table(report: AggregateReport, *, console: Console | None = None) -> None:
    console = console or Console()
    console.rule(f"[bold]Aggregate — {report.session_count} session(s)")

    if report.session_count == 0:
        console.print("[dim]no sessions matched[/dim]")
        return

    tab = Table(box=box.SIMPLE_HEAVY)
    tab.add_column("session", style="cyan", overflow="fold")
    tab.add_column("turns", justify="right")
    tab.add_column("cost ($)", justify="right")
    tab.add_column("leak ($)", justify="right")
    tab.add_column("leak %", justify="right")
    tab.add_column("dominant lever", overflow="fold")
    tab.add_column("outlier", justify="center")

    for s in report.sessions:
        outlier_marker = "[red]⚠ OUTLIER[/red]" if s.is_outlier else ""
        leak_pct = s.leak_ratio * 100
        tab.add_row(
            s.label,
            f"{s.turn_count:,}",
            f"{s.total_cost_usd:.4f}",
            f"{s.effective_leak_cost_usd:.4f}",
            f"{leak_pct:.1f}%",
            s.dominant_lever or "",
            outlier_marker,
        )
    console.print(tab)

    total_turns = sum(s.turn_count for s in report.sessions)
    leak_pct = (
        (report.total_effective_leak_usd / report.total_cost_usd * 100)
        if report.total_cost_usd > 0 else 0.0
    )
    console.print(
        f"[bold]Total:[/bold] {total_turns:,} turns / "
        f"${report.total_cost_usd:.4f} cost / "
        f"${report.total_effective_leak_usd:.4f} effective leak "
        f"({leak_pct:.1f}%)"
    )
    median_pct = report.median_leak_ratio * 100
    threshold_pct = report.outlier_threshold * 100
    console.print(
        f"[dim]Median session leak: {median_pct:.1f}%, "
        f"outlier threshold: {threshold_pct:.1f}%[/dim]"
    )


def render_json(report: AggregateReport) -> str:
    payload = {
        "session_count": report.session_count,
        "total_cost_usd": report.total_cost_usd,
        "total_effective_leak_usd": report.total_effective_leak_usd,
        "median_leak_ratio": report.median_leak_ratio,
        "outlier_threshold": report.outlier_threshold,
        "sessions": [
            {**asdict(s), "path": str(s.path)} for s in report.sessions
        ],
    }
    return _json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Update `tlp/aggregate/__init__.py`**

```python
from tlp.aggregate.types import SessionRow, AggregateReport
from tlp.aggregate.run import expand_paths, aggregate
from tlp.aggregate.reporter import render_table, render_json

__all__ = [
    "SessionRow", "AggregateReport",
    "expand_paths", "aggregate",
    "render_table", "render_json",
]
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/test_aggregate.py -v
uv run pytest -q
```

Expected: all aggregate tests pass; full suite green.

- [ ] **Step 6: Commit**

```bash
git add tlp/aggregate/reporter.py tlp/aggregate/__init__.py tests/test_aggregate.py
git commit -m "feat(aggregate): rich table + JSON renderers with outlier marker"
```

---

## Task 8: CLI aggregate subcommand

**Files:**
- Modify: `tlp/cli.py`
- Modify: `tests/test_cli_e2e.py`

- [ ] **Step 1: Write failing tests (append)**

Append to `tests/test_cli_e2e.py`:

```python
def test_aggregate_directory_table():
    fix_dir = "tests/fixtures/synthetic/aggregate"
    r = _run("aggregate", fix_dir)
    assert r.returncode == 0, r.stderr
    assert "Aggregate" in r.stdout
    assert "Total:" in r.stdout


def test_aggregate_json_output():
    fix_dir = "tests/fixtures/synthetic/aggregate"
    r = _run("aggregate", fix_dir, "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["session_count"] == 2
    assert "outlier_threshold" in data


def test_aggregate_two_files_explicit():
    r = _run(
        "aggregate",
        "tests/fixtures/synthetic/aggregate/session_normal.jsonl",
        "tests/fixtures/synthetic/aggregate/session_outlier.jsonl",
        "--format", "json",
    )
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["session_count"] == 2


def test_aggregate_missing_path_exit_1():
    r = _run("aggregate", "/nonexistent/dir/")
    assert r.returncode == 1


def test_aggregate_empty_dir_exit_0_no_sessions(tmp_path):
    r = _run("aggregate", str(tmp_path))
    assert r.returncode == 0
    assert "no sessions matched" in r.stdout.lower() or "no sessions matched" in r.stderr.lower()
```

- [ ] **Step 2: Run tests to verify fail**

```bash
uv run pytest tests/test_cli_e2e.py -v
```

Expected: 5 new tests FAIL (no `aggregate` subcommand).

- [ ] **Step 3: Modify `tlp/cli.py`**

Add the new subcommand. Insert these imports near the top with the other tlp imports:

```python
from tlp.aggregate import aggregate as aggregate_run, render_table as agg_render_table, render_json as agg_render_json
```

Then add a new `@app.command(name="aggregate")` function below the existing `schema_dump` command:

```python
@app.command(name="aggregate")
def aggregate(
    paths: list[Path] = typer.Argument(..., help="One or more .jsonl files or directories"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    outlier_multiplier: Optional[float] = typer.Option(
        None, "--outlier-multiplier",
        help="override aggregate.outlier_multiplier (default 2.0)",
    ),
    min_confidence: str = typer.Option("mid", "--min-confidence", help="low | mid | high"),
) -> None:
    """Aggregate multiple session transcripts with median-based outlier flagging."""
    if format not in ("table", "json"):
        typer.echo("error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)
    for p in paths:
        if not p.exists():
            typer.echo(f"error: file not found: {p}", err=True)
            raise typer.Exit(code=1)

    try:
        report = aggregate_run(
            paths,
            config_path=config_path,
            pricing_path=pricing_path,
            outlier_multiplier=outlier_multiplier,
            min_confidence=min_confidence,
        )
    except FileNotFoundError as e:
        typer.echo(f"error: file not found: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    if report.session_count == 0:
        typer.echo("no sessions matched")
        return

    if format == "json":
        out = agg_render_json(report)
        if output:
            output.write_text(out)
        else:
            sys.stdout.write(out + "\n")
    else:
        agg_render_table(
            report,
            console=Console(force_terminal=False if not sys.stdout.isatty() else None),
        )
```

Make sure `from typing import Optional` and `from pathlib import Path` are already present at the top of the file (they were added in v0.2 — verify by grep).

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_cli_e2e.py -v
uv run pytest -q
```

Expected: all e2e tests pass; full suite green.

- [ ] **Step 5: Smoke test against real session dir**

```bash
uv run tlp aggregate ~/.claude/projects/-home-ljk9121-projects-leejk/
```

Expected: rich table with multiple session rows; outlier (likely `5c7286b1` or another) flagged. If no real leejk transcripts exist, skip.

- [ ] **Step 6: Commit**

```bash
git add tlp/cli.py tests/test_cli_e2e.py
git commit -m "feat(cli): tlp aggregate subcommand"
```

---

## Task 9: Version bump + README + pyproject sync

**Files:**
- Modify: `tlp/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Bump version in `tlp/__init__.py`**

```python
__version__ = "0.3.0"
```

- [ ] **Step 2: Bump version in `pyproject.toml`**

Find the `version = "0.2.0"` line and change to:

```toml
version = "0.3.0"
```

This synchronization was missed in v0.2 — final reviewer flagged it. Don't repeat the same mistake.

- [ ] **Step 3: Update `README.md`**

Find the `## Usage` section and add an `aggregate` example right after the existing `tlp analyze` example. The new block:

```markdown
## Usage

    uv run tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

Aggregate multiple sessions in a project directory:

    uv run tlp aggregate ~/.claude/projects/<slug>/
```

Then near the bottom (after the existing usage tips), update any stale wording. Specifically: if the description line says anything like "single-session profiler", change it to mention multi-session aggregation too. Use grep to find:

```bash
grep -n "single-session\|6 levers\|all 7" README.md
```

Update each match to be accurate for v0.3.

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
```

Expected: all tests pass (final count: ~96 = 80 v0.2 + ~16 added across v0.3 tasks).

- [ ] **Step 5: Verify version sync**

```bash
uv run python -c "import tlp; print(tlp.__version__)"
grep '^version' pyproject.toml
```

Expected: both print `0.3.0`.

- [ ] **Step 6: Commit**

```bash
git add tlp/__init__.py pyproject.toml README.md
git commit -m "docs: bump version to 0.3.0 + add aggregate to README"
```

---

## Self-Review

**Spec coverage:**

| Spec § | Implemented in |
|---|---|
| §1 Goal A (aggregate) | Tasks 5, 6, 7, 8 |
| §1 Goal B (tools_changed absorption) | Task 3 |
| §1 Goal C (reasoning_overrun split) | Task 4 |
| §2 Inputs (schema-discovery evidence) | reference only — informs Tasks 2 (ai-title), 3 (tools_changed) |
| §3 Architecture file structure | Tasks 5–8 create the new module exactly per spec |
| §4 ParsedTrace.label | Task 1 |
| §4 SessionRow / AggregateReport | Task 5 |
| §5.1 ai-title parser change | Task 2 |
| §5.2 tools_changed parser change | Task 3 |
| §6 reasoning_overrun split | Task 4 |
| §7 CLI three subcommands | Task 8 (aggregate added; analyze + schema-dump untouched) |
| §8 Aggregate algorithm | Task 6 |
| §9 Output formats | Task 7 |
| §10 Config: aggregate.outlier_multiplier | Task 6 Step 1 |
| §11 Error handling | Task 8 (CLI exit codes) + Task 6 (FileNotFoundError raising) |
| §12 Testing strategy (regression + new) | Every task ships TDD tests; total adds ~16 |
| §13 No new deps | Verified — stdlib `statistics` only |
| §14 Migration / version | Task 9 |
| §15 v0.4+ backlog | Reference only |
| §16 Open Questions | Decisions deferred per spec |

**Placeholder scan:** No "TBD/TODO" in any step. Each code step has complete code. Each command has expected output. Task 9 Step 3 uses a grep loop ("Update each match") — this is a deliberate hand-step because README's exact current wording isn't statically known; the grep command shows exactly what to look at.

**Type consistency:**
- `ParsedTrace.label: str | None = None` (Task 1) used by Task 2 (set on return), Task 6 (read in row construction). ✓
- `SessionRow` field names (Task 5) match those constructed in Task 6 and consumed in Task 7. ✓
- `AggregateReport` field names (Task 5) consistent across `aggregate()` (Task 6), `render_table` (Task 7), `render_json` (Task 7), CLI (Task 8). ✓
- `expand_paths` signature (Task 6) called by `aggregate()` and tested in Task 6 — same signature. ✓
- reasoning_overrun split locations `turn[N].dup` / `turn[N].ratio` (Task 4) — consistent across spec, code, and tests. ✓

No gaps found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-token-leak-profiler-v0.3.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance then code quality), fast iteration.
2. **Inline Execution** — execute in this session using executing-plans with batch checkpoints.

Which approach?
