# Token Leak Profiler v0.3 — Design Spec

- **Date**: 2026-05-28
- **Owner**: ljk9121
- **Status**: Approved (brainstorming) → ready for implementation plan
- **Builds on**: [v0.2 design](2026-05-28-token-leak-profiler-v2-design.md), [v0.1 design](2026-05-28-token-leak-profiler-design.md)
- **Spec-checklist applied**: yes (see §2)

## 1. Goal & Scope

### Why v0.3 (the rename from "v2")

v0.2.0 shipped under the name "v2" but in retrospect was a `v1.x` cleanup + one new lever. The real v2-class change — multi-session aggregation — never landed. v0.3 corrects the naming and ships the actual aggregate feature, plus two diagnostic fixes that schema-discovery (per `docs/spec-checklist.md`) surfaced *before* data model design.

### Three concurrent changes

- **A (aggregate)** — `tlp aggregate <path>...` subcommand. Runs the full analyzer set against every session in a directory or file list, emits a per-session table with auto-flagged outliers. AI-title extracted as human-readable session label.
- **B (`tools_changed` event absorption)** — schema-discovery found Claude Code emits 11 `tools_changed` events on the dogfooding session; each is a real assistant message (`output_tokens=1538`+) with its own thinking/tool_use content. v0.2.0 parser skips these → real cost is under-reported. v0.3 absorbs them as assistant messages and lets the existing `message.id` dedup handle bookkeeping.
- **C (reasoning_overrun split)** — final v0.2 review flagged that `dup_tokens > 0` lumps the `overrun` portion (still ratio-signal) under `evidence_kind="confirmed"`. v0.3 emits two separate Findings per affected turn: `turn[N].dup` (confirmed) and `turn[N].ratio` (signal).

### v0.3 Non-Goals

- `tool_schema_bloat` redefinition — schema-discovery found Claude Code transcripts have **no raw `tools` definition payload** (defs are client-side, baked into the binary). The current analyzer is structurally meaningless in this context. Reframing it requires a different algorithm (call-frequency-based?) — v0.4.
- Provider adapters (OpenAI/Gemini) — v0.4+.
- Simulation (apply-suggestion-recompute) — v0.4+ after `tool_schema_bloat` is repaired.
- Cross-session pattern detection (lever common to ≥3 sessions, time-series) — v0.4 backlog.
- Markdown / HTML reports — v0.4+.

## 2. Inputs & Schema-Discovery Evidence

### Input format
Unchanged from v0.2: Claude Code session transcripts. For `aggregate`, the input is a list of paths where each path is either a `.jsonl` file or a directory (recursively scanned for `*.jsonl`).

### Schema-discovery dump (3 real sessions)

Per `docs/spec-checklist.md`, ran `tlp schema-dump` on three representative sessions *before* writing data model. Findings shaped the v0.3 scope:

**Session af0b624f (tlp v0.2 dev, 1136 events)**
- event types: `assistant=486 user=312 last-prompt=63 mode=63 permission-mode=63 ai-title=62 file-history-snapshot=34 attachment=29 system=22 queue-operation=2`
- assistant blocks: `tool_use=283 text=104 thinking=102`
- message.id: `unique=168 max_repeat=20 mean_repeat=2.89`
- thinking blocks: `visible=0 redacted=102`
- tools defined: `[]` ← unexpected (see below)
- tools called: `[Agent, AskUserQuestion, Bash, Edit, Read, Skill, TaskCreate, TaskUpdate, ToolSearch, Write]`
- usage: `input=321 output=349,701 cache_read=43,125,755 cache_creation=2,013,453`
- skipped: `last-prompt(63) mode(63) permission-mode(63) ai-title(62) file-history-snapshot(34) attachment(29) system(22) queue-operation(2)`

**Session d1fa51cc (leejk small, 148 events)**
- event types: `assistant=55 user=33 attachment=11 last-prompt=10 mode=10 permission-mode=10 ai-title=9 file-history-snapshot=6 system=4`
- message.id: `unique=19 max_repeat=8 mean_repeat=2.89`
- thinking blocks: `visible=0 redacted=12`

**Session 5c7286b1 (leejk outlier, 261 events)**
- event types: `assistant=85 user=56 last-prompt=22 permission-mode=22 ai-title=21 system=21 file-history-snapshot=19 attachment=15`
- message.id: `unique=55 max_repeat=3 mean_repeat=1.55`
- thinking blocks: `visible=0 redacted=26`

### Structural decisions from discovery

1. **`ai-title` events carry session titles.** Every session has ≥1 `ai-title` event with human-readable label. Extracting this is essential for aggregate output ("which session is the outlier?").
2. **`tools_changed` events are full assistant messages.** Schema-dump above shows them grouped under `assistant` count because dump treats them per content-block; raw inspection (see brainstorming notes) confirms `tools_changed` has `message.role="assistant"`, `usage.output_tokens > 0`. v0.2 parser skips by `ev_type` filter → real cost under-reported.
3. **All thinking blocks are redacted (`visible=0`).** No fixture in v0.1/v0.2 exercised visible thinking against real data; this is expected for production Claude Code workloads.
4. **`tools defined: []` everywhere.** Claude Code transcripts never contain raw tool schema definitions — those live in the binary. `tool_schema_bloat` analyzer is structurally inapplicable. Deferred to v0.4 redesign.
5. **`message.id` mean_repeat 1.5–2.9** confirms v0.2.0 parser's global non-consecutive dedup is needed and working.
6. **Event types accounted for**: every type appearing in any dump is either parsed (`user`, `assistant`, now `tools_changed`) or explicitly listed in `_skipped_event_types` (`mode`, `permission-mode`, `last-prompt`, `ai-title`, `file-history-snapshot`, `attachment`, `system`, `queue-operation`). `ai-title` moves from "skipped" to "parsed for label extraction" in v0.3.

### Output

**`tlp aggregate` (new):** rich table by default with per-session row + outlier flag; `--format json` for machine-readable.

**`tlp analyze` (unchanged):** existing v0.2 output, but reasoning_overrun now emits two findings per affected turn (split).

**`tlp schema-dump` (unchanged):** existing.

Exit codes per v0.2: 0 normal, 1 user error, 2 internal.

## 3. Architecture

Unchanged at the top level: Registry + ParsedTrace. New module `tlp/aggregate/`, parser edits, one analyzer edit.

```
token-leak-profiler/
  tlp/
    __init__.py                     # MODIFY: __version__ 0.2.0 → 0.3.0
    types.py                        # MODIFY: ParsedTrace.label field
    parser/
      claude_code.py                # MODIFY: ai-title label extract, tools_changed absorb
    analyzers/
      reasoning_overrun.py          # MODIFY: split into two Findings (dup + ratio)
    aggregate/                      # NEW
      __init__.py                   # re-export aggregate, AggregateReport, SessionRow
      types.py                      # SessionRow, AggregateReport dataclasses
      run.py                        # expand_paths, aggregate()
      reporter.py                   # render_table, render_json (aggregate-specific)
    cli.py                          # MODIFY: aggregate subcommand
    config/
      defaults.yaml                 # MODIFY: aggregate.outlier_multiplier
  tests/
    fixtures/synthetic/
      ai_title_trace.jsonl          # NEW (single-event ai-title + minimal session)
      tools_changed_trace.jsonl     # NEW (assistant + tools_changed both with usage)
      visible_thinking_split.jsonl  # NEW (visible thinking with both dup and overrun)
      aggregate/                    # NEW subdir of 2-3 small session fixtures
        session_normal.jsonl
        session_outlier.jsonl
    test_parser.py                  # EXTEND: ai-title label, tools_changed absorption
    test_analyzers/
      test_reasoning_overrun.py     # EXTEND/REVISE: split-into-two assertions
    test_aggregate.py               # NEW (expand_paths, aggregate logic, outlier flag)
    test_cli_e2e.py                 # EXTEND: aggregate subprocess test
  docs/superpowers/
    specs/2026-05-28-token-leak-profiler-v0.3-design.md   # this file
```

Boundary preservation:
- `aggregate/` doesn't depend on `cli.py`. It is callable by libraries.
- `aggregate/reporter.py` is separate from `reporter/` (single-session) to avoid coupling — single-session reporter expects `LeakReport` list; aggregate reporter expects `AggregateReport`.

## 4. Data Model Changes

### `ParsedTrace.label` (new optional field)

```python
@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable
    label: str | None = None        # NEW: from first ai-title event; None if absent
```

Default `None` keeps v0.2 callers backward-compat (single-session reporter ignores label).

### `SessionRow` and `AggregateReport`

```python
# tlp/aggregate/types.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    label: str                              # ai-title text or session_id[:8] fallback
    path: Path
    turn_count: int
    total_cost_usd: float
    effective_leak_cost_usd: float
    leak_ratio: float                       # effective_leak / max(total_cost, ε)
    dominant_lever: str | None              # lever name with highest leaked_tokens (or None)
    is_outlier: bool


@dataclass(frozen=True)
class AggregateReport:
    sessions: tuple[SessionRow, ...]
    total_cost_usd: float
    total_effective_leak_usd: float
    median_leak_ratio: float
    outlier_threshold: float                # median_leak_ratio × outlier_multiplier
    session_count: int                      # = len(sessions); cached for clarity
```

Both frozen — read-only output containers.

## 5. Parser Changes

### 5.1 `ai-title` event → ParsedTrace.label

First pass adds a single field collection. After loop ends, `label` is set on the returned `ParsedTrace`:

```python
ai_title: str | None = None  # initialize before loop

for raw_line, line_no in _iter_lines(path):
    ...
    event = json.loads(raw_line)
    ...
    if event.get("type") == "ai-title" and ai_title is None:
        msg = event.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                ai_title = content.strip()
        # skip — don't add to events list, don't increment usage
        continue
    ...

# When returning ParsedTrace:
return ParsedTrace(..., label=ai_title)
```

If absent, label stays None. Aggregate output falls back to `session_id[:8]`.

### 5.2 `tools_changed` event → treat as assistant message

Current parser line:
```python
if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
    # skip
```

Replace with:
```python
if ev_type == "tools_changed":
    ev_type = "assistant"            # normalize for downstream
if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
    # skip
```

`message.id` global dedup (added in v0.2 fix `960f5a4`) ensures `tools_changed` events sharing an id with a prior `assistant` event don't double-count usage. Events with their own unique id contribute their full usage (correct behavior — they are real billed messages).

### 5.3 No change to other event handling

`mode`, `permission-mode`, `last-prompt`, `file-history-snapshot`, `attachment`, `system`, `queue-operation` continue to be skipped (added to `_skipped_event_types` counters). These do not carry billed `usage`.

## 6. reasoning_overrun Finding Split

### Current (v0.2.0)
Single Finding per affected turn. `evidence_kind` chosen by `if dup_tokens > 0` → confirmed-or-signal-for-whole. final review flagged this conflates measurement with signal.

### v0.3
Per affected turn, emit up to two Findings:

```python
# After computing dup_tokens and overrun for this turn:
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

Total `leaked_tokens` on the report equals `sum(dup) + sum(overrun)` — same magnitude as v0.2.0, but split across `confirmed_tokens` and `signal_tokens` on the report.

### Test consequences
- `test_visible_thinking_duplicate_sentence_is_confirmed` (v0.2.0): currently asserts ≥1 confirmed finding with confidence `"mid"`. Stays valid — assert on the `.dup` finding.
- `test_redacted_thinking_is_signal_not_confirmed` (v0.2.0): currently asserts `findings[0].evidence_kind == "signal"`. With redacted-only path, only `overrun > 0` fires → still one finding, still signal. Test stays valid (since dup_tokens=0 for redacted).
- New: `test_visible_thinking_emits_both_dup_and_ratio` — fixture with visible thinking that triggers both paths, assert exactly 2 findings with distinct evidence_kinds.

## 7. CLI Changes

Three subcommands now:

```
tlp analyze <path> [options]                    # unchanged
tlp schema-dump <path> [--format text|json]     # unchanged
tlp aggregate <path>... [options]               # NEW
```

### `tlp aggregate` options

```
--format {table,json}              default: table
--output PATH                      write JSON to file
--config PATH                      defaults.yaml override
--pricing PATH                     pricing.yaml override
--outlier-multiplier FLOAT         override aggregate.outlier_multiplier (default 2.0)
--min-confidence {low,mid,high}    findings filter applied to each session (default mid)
```

### CLI flow
1. Validate every input path exists (nonexistent → exit 1). Collect `expand_paths(paths)` → list of `.jsonl` files.
2. If zero files matched (e.g., empty directory or directory with no `.jsonl`) → print `no sessions matched` and exit 0 (consistent with §11 — empty result is not an error).
3. For each file: `parse()` → run all analyzers → compute `effective_leak_cost_usd` using the same blended-rate math as single-session reporter.
4. Build `SessionRow` per file.
5. Compute `median_leak_ratio`, `outlier_threshold = median × multiplier`. Mark `is_outlier` on each row.
6. Emit via `aggregate.reporter.render_table(...)` or `render_json(...)`.

### `expand_paths(paths)` semantics
- Path is a regular file ending in `.jsonl` → include directly.
- Path is a directory → glob `**/*.jsonl` recursively (sorted by filename for determinism).
- Path doesn't exist → raise `FileNotFoundError` (CLI maps to exit 1).
- Path ending in `.jsonl` but doesn't exist → raise (same).

## 8. Aggregate Algorithm Detail

```python
# tlp/aggregate/run.py
from __future__ import annotations
import statistics
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.aggregate.types import SessionRow, AggregateReport


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

    multiplier = outlier_multiplier or float(
        config.get("aggregate", {}).get("outlier_multiplier", 2.0)
    )

    rows: list[SessionRow] = []
    for f in files:
        trace = parse(f, pricing=pricing)
        reports = _run_analyzers(trace, config, min_confidence)
        bucket_map = {r.analyzer: _bucket_for(r.analyzer) for r in reports}
        total_cost = _total_cost(trace)
        eff_leak = _effective_leak(trace, reports, bucket_map)
        leak_ratio = eff_leak / max(total_cost, 1e-9)
        dominant = (
            max(reports, key=lambda r: r.leaked_tokens).analyzer
            if reports and any(r.leaked_tokens > 0 for r in reports)
            else None
        )
        rows.append(SessionRow(
            session_id=trace.session_id,
            label=trace.label or (trace.session_id[:8] if trace.session_id else "<unknown>"),
            path=f,
            turn_count=len(trace.turns),
            total_cost_usd=total_cost,
            effective_leak_cost_usd=eff_leak,
            leak_ratio=leak_ratio,
            dominant_lever=dominant,
            is_outlier=False,  # filled in next pass
        ))

    if not rows:
        return AggregateReport(
            sessions=(), total_cost_usd=0.0, total_effective_leak_usd=0.0,
            median_leak_ratio=0.0, outlier_threshold=0.0, session_count=0,
        )

    median_ratio = statistics.median(r.leak_ratio for r in rows)
    threshold = median_ratio * multiplier
    flagged = tuple(
        SessionRow(
            **{**row.__dict__, "is_outlier": row.leak_ratio > threshold}
        )
        for row in rows
    )

    return AggregateReport(
        sessions=flagged,
        total_cost_usd=sum(r.total_cost_usd for r in flagged),
        total_effective_leak_usd=sum(r.effective_leak_cost_usd for r in flagged),
        median_leak_ratio=median_ratio,
        outlier_threshold=threshold,
        session_count=len(flagged),
    )


# Internal helpers _run_analyzers, _bucket_for, _total_cost, _effective_leak
# duplicate small portions of the single-session reporter logic; keep them
# private and ≤ 30 lines each. Reuse PricingTable.cost for math.
```

`is_outlier` updated via re-construction because `SessionRow` is frozen.

### Edge cases
- **Single session input**: median = its own ratio, threshold = ratio × multiplier > ratio → `is_outlier = False`. Acceptable (no comparison group).
- **All sessions identical leak_ratio = 0**: threshold = 0, `is_outlier = False` for all (no waste). Correct.
- **Zero files matched**: empty AggregateReport, CLI prints "no sessions matched" and exits 0.

## 9. Output Formats

### Table

```
────── Aggregate — 4 sessions ──────

  session                                 turns   cost ($)   leak ($)   leak %  dominant lever          outlier
 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
  v2 implementation                         391    19.984     1.842      9.2%   cache_miss_penalty
  Personal site — homepage tweaks            64     1.651     0.168     10.2%   reasoning_overrun
  Personal site — i18n refactor             162     4.713     0.395      8.4%   reasoning_overrun
  Personal site — outlier session           111     5.652     1.660     29.4%   reasoning_overrun       ⚠ OUTLIER

Total: 728 turns / $31.999 cost / $4.065 effective leak (12.7%)
Median session leak: 9.7%, outlier threshold: 19.5% (×2.0 median)
```

Rendered with `rich`. Outlier rows: `⚠ OUTLIER` marker in last column, red style. Empty cells for `dominant_lever=None`.

### JSON

```json
{
  "session_count": 4,
  "total_cost_usd": 31.999,
  "total_effective_leak_usd": 4.065,
  "median_leak_ratio": 0.097,
  "outlier_threshold": 0.195,
  "outlier_multiplier": 2.0,
  "sessions": [
    {
      "session_id": "af0b624f-...",
      "label": "v2 implementation",
      "path": "/home/.../af0b624f-...jsonl",
      "turn_count": 391,
      "total_cost_usd": 19.984,
      "effective_leak_cost_usd": 1.842,
      "leak_ratio": 0.092,
      "dominant_lever": "cache_miss_penalty",
      "is_outlier": false
    }
  ]
}
```

## 10. Config Changes

`tlp/config/defaults.yaml` adds:

```yaml
aggregate:
  outlier_multiplier: 2.0
```

All other v0.2 keys unchanged.

## 11. Error Handling

- **Path doesn't exist**: CLI exit 1 with `error: file not found: <path>`.
- **No `.jsonl` files matched in any input**: CLI exit 0, print "no sessions matched". (Empty aggregate is not an error.)
- **A single transcript fails to parse**: warn and skip (consistent with single-session `--strict=False`); rest of the sessions continue.
- **All transcripts fail to parse**: empty report, exit 0 with warning summary on stderr.

## 12. Testing Strategy

### v0.2.0 regression
All 80 v0.2.0 tests must stay green. The biggest backward-compat risk is the reasoning_overrun split — explicitly update affected tests rather than relying on default behavior.

### New unit tests
- `tests/test_aggregate.py`:
  - `expand_paths`: single file, single dir, mixed list, nested dir, missing path raises, non-jsonl files filtered out.
  - `aggregate` empty input → empty report (no exception).
  - `aggregate` single session → no outlier (single-member median check).
  - `aggregate` 3 sessions with one obvious outlier (leak_ratio 0.3 vs 0.05 × 2) → flagged.
  - `aggregate` all-zero leaks → no outliers.
- `tests/test_parser.py` extensions:
  - `ai-title` event → `ParsedTrace.label` populated; absent → None.
  - `tools_changed` event → counted as assistant turn, `message.id` dedup handles repeats.
- `tests/test_analyzers/test_reasoning_overrun.py` revisions:
  - `test_visible_thinking_emits_both_dup_and_ratio` (new): visible thinking with both signals → exactly 2 findings with distinct kinds and locations (`.dup`, `.ratio`).
  - Update existing assertions to reference `.dup` / `.ratio` locations explicitly.

### New e2e tests
- `tests/test_cli_e2e.py`:
  - `tlp aggregate <fixture_dir>` exit 0, JSON parses, session_count > 0.
  - `tlp aggregate <single_file>` works (file-not-dir branch).
  - `tlp aggregate /nonexistent` exit 1.
  - `tlp aggregate` with no args → help (typer default).

### New fixtures
- `tests/fixtures/synthetic/ai_title_trace.jsonl` — single trace with one `ai-title` event + minimal user/assistant.
- `tests/fixtures/synthetic/tools_changed_trace.jsonl` — assistant message + tools_changed message (different `message.id`), both with usage; total usage sums correctly.
- `tests/fixtures/synthetic/visible_thinking_split.jsonl` — visible thinking with both duplicate sentence pair AND high overrun ratio → exercises split path.
- `tests/fixtures/synthetic/aggregate/session_normal.jsonl`, `aggregate/session_outlier.jsonl` — small (5–10 turn) sessions where the outlier has leak_ratio ≥ 2× the normal one.

### Coverage targets
Unchanged: analyzers ≥ 90%, parser ≥ 95%, aggregate ≥ 90%.

## 13. Dependencies & Runtime

- Stdlib only: `statistics` (median calc), `pathlib` (rglob).
- No new third-party packages.

## 14. Migration & Versioning

- `tlp/__init__.py` `__version__ = "0.3.0"`.
- `pyproject.toml` version bumped synchronously (lesson from v0.2.0 final review).
- README: bump "7 levers" copy if anything stale.
- Backward-compat: `tlp analyze` and `tlp schema-dump` outputs unchanged at the JSON schema level *except* reasoning_overrun's `findings[]` now contains up to twice as many items per turn. Any consumer iterating findings without assumptions about count is fine; consumers depending on "one finding per turn" must update.

## 15. v0.4+ Backlog

- **`tool_schema_bloat` redefinition** — current algorithm assumes raw `tools` definitions in transcript; Claude Code has none. Reframe as "tool with low call frequency per turn × turns it was advertised" or similar. Requires new lever spec.
- Cross-session pattern detection — lever common to N% of sessions.
- Time-series view (cost trend over date).
- Markdown / HTML report.
- OpenAI / Gemini provider adapters.
- Simulation: apply suggestion, recompute totals.
- pyproject entry-points for external analyzer plug-ins.

## 16. Open Questions

- **Outlier threshold floor**: if `median_leak_ratio = 0` (all sessions zero leak), threshold becomes 0 → no outliers. Acceptable. But if median is *very small* (e.g., 0.001), threshold of 0.002 may flag noise. Consider floor like `max(median × multiplier, 0.05)` after real-data calibration. Decide during implementation by running aggregate on the 11 known sessions.
- **Outlier on single-session input**: spec says no outlier. If user passes one session, the command still completes useful work (per-session row, no comparison). Confirm by usage in dogfooding.
