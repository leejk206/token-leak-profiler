# Token Leak Profiler v2 — Design Spec

- **Date**: 2026-05-28
- **Owner**: ljk9121
- **Status**: Approved (brainstorming) → ready for implementation plan
- **Builds on**: [v1 design](2026-05-28-token-leak-profiler-design.md)

## 1. Goal & Scope

### Why v2

Dogfooding v1 on four real Claude Code sessions revealed three structural gaps:

1. **`leaked_tokens` semantics are inconsistent across levers.** Five levers (stale_context, redundant_restatement, tool_schema_bloat, verbose_tool_results, format_boilerplate) measure tokens by inspecting *content*. `reasoning_overrun` measures a *ratio* (thinking ÷ productive output) and cannot inspect content when thinking is server-redacted. Both report under the same `leaked_tokens` field, so totals overstate "waste" by mixing measurement with signal.

2. **One real leak class isn't covered.** Anthropic prompt caching reuses identical prefixes at `cache_read` ($0.30/Mtok). When the prefix changes turn-to-turn (dynamic timestamps, mutating session metadata at the tail), the session re-pays `cache_creation` ($3.75/Mtok). v1 has no analyzer for this pattern, which on real workloads can be more expensive than every other lever combined.

3. **Input schema gets assumed instead of inspected.** v1 spec §2 was a one-liner ("Claude Code transcript JSONL"). The dogfooding parser bug (streaming events per content block, repeated `usage`) and the redacted-thinking miss both stem from this. Future spec rounds need a checkpoint that forces structural discovery before data model design.

### v2 Goal

Three concurrent, scoped changes:

- **A (precision)** — Split confirmed measurement from signal-only attention. Add `evidence_kind` to `Finding`. Reporter shows two separate totals.
- **B (coverage)** — Add `cache_miss_penalty` analyzer.
- **C (process)** — Add `tlp schema-dump` subcommand and a spec checklist doc so the next spec round can't skip schema discovery.

### v2 Non-Goals

- Multi-session aggregation (`tlp aggregate`) — v2.1.
- OpenAI / Gemini provider adapters — v2.x.
- Savings simulation (apply-and-recompute) — needs precision foundation; v3.
- Live tap via Anthropic SDK middleware — out of scope.
- `unbounded_growth` lever — partial overlap with `redundant_restatement`; v2.x backlog.
- Embedding-based lever upgrades — v3.

## 2. Inputs & Outputs

### Input
Unchanged from v1: Claude Code session transcript JSONL.

Schema discovery dump from three real sessions (`tlp schema-dump` output) attached as evidence for spec assumptions (see §9):

- Event types observed: `assistant`, `user`, plus metadata types we already skip (`mode`, `attachment`, `summary`, `system`, `tools_changed`, `task_reminder`, `mcp_instructions_delta`, `hook_*`, `tool_reference`, `skill_listing`, `create`, `command_permissions`, `deferred_tools_delta`).
- Assistant content block types: `text`, `tool_use`, `thinking`. Thinking blocks observed with empty `thinking` field and `signature` (redacted variant). v2 keeps the same parser handling; the schema-dump tool surfaces this explicitly for any new transcript a future spec round encounters.
- `message.id` repeats across consecutive events (streaming split). v1.1 parser fix groups by `message.id`; v2 preserves that behavior.

### Output (v2)

**`tlp analyze` (existing command, output extended):**

- Default rich CLI table:
  - Header (unchanged from v1.1): turns / fresh input / output / cost; cache_read; cache_creation.
  - Lever summary table gains two columns: `confirmed tok` and `signal tok` (in place of single `tokens` column).
  - Two summary lines replace the single "Estimated total leak":
    - `Confirmed leak: X tok / $Y` — content-based measurement
    - `Attention signals: X tok / $Y (high thinking-ratio etc., not proven waste)`
  - `Effective leak (cache-adjusted)` line stays as a third summary line.
  - Per-lever findings table gains a `kind` column (`CONF` / `SIG`).
- `--format json`:
  - Top-level adds `confirmed_leak_cost_usd` and `signal_attention_cost_usd` (the latter replaces `total_effective_leak_cost_usd` — same math, more honest name).
  - Each report adds `confirmed_tokens` and `signal_tokens` breakdown; `leaked_tokens` remains as the sum.
  - Each finding adds `evidence_kind`.

**`tlp schema-dump` (new subcommand):**

- `tlp schema-dump <transcript.jsonl> [--format text|json]`
- Output (text default; see §6 for json shape):
  ```
  == Session af0b624f-... ==
  events: 720
  event types:       assistant=240  user=158  summary=31  mode=31  ...
  assistant blocks:  text=149  tool_use=146  thinking=50
  user blocks:       text=158  tool_result=146
  message.id:        unique=180  max_repeat=3  mean_repeat=1.33
  thinking blocks:   visible=0  redacted(signature)=50
  tools defined:     ['Read','Write','Edit','Bash',...]
  tools called:      ['Read','Bash','Edit','Write',...]
  usage totals:      input(fresh)=449  output=651,560  cache_read=33,534,006  cache_creation=1,393,913
  skipped events:    mode(31), attachment(13), summary(31), ...
  ```

Exit codes unchanged from v1.

## 3. Architecture

Unchanged from v1: Registry + `ParsedTrace`. Three concrete edits:

1. `tlp/types.py` — `Finding` gains `evidence_kind`; `LeakReport` gains `confirmed_tokens` / `signal_tokens` properties.
2. `tlp/analyzers/cache_miss_penalty.py` — new analyzer auto-registers.
3. `tlp/cli.py` — multi-command (typer `@app.command()` × 2). Removes the `_noop` workaround left over from v1 Task 16.

```
token-leak-profiler/
  tlp/
    types.py                       # MODIFIED: Finding.evidence_kind, LeakReport properties
    analyzers/
      cache_miss_penalty.py        # NEW
      reasoning_overrun.py         # MODIFIED: per-finding evidence_kind branching
      stale_context.py             # MODIFIED: explicit evidence_kind="confirmed"
      redundant_restatement.py     # MODIFIED: explicit evidence_kind="confirmed"
      tool_schema_bloat.py         # MODIFIED: explicit evidence_kind="confirmed"
      verbose_tool_results.py      # MODIFIED: explicit evidence_kind="confirmed"
      format_boilerplate.py        # MODIFIED: explicit evidence_kind="confirmed"
    reporter/
      json_renderer.py             # MODIFIED: confirmed/signal breakdown fields
      table.py                     # MODIFIED: two-line summary + kind column
    cli.py                         # MODIFIED: schema-dump subcommand, remove _noop
    schema/                        # NEW
      __init__.py
      dump.py                      # ParsedTrace + raw events → schema report
    config/
      defaults.yaml                # MODIFIED: cache_miss_penalty thresholds
  tests/
    fixtures/synthetic/
      cache_miss_trace.jsonl       # NEW
    test_analyzers/
      test_cache_miss_penalty.py   # NEW
      test_reasoning_overrun.py    # EXTENDED: visible-thinking confirmed assertion
    test_reporter.py               # EXTENDED: confirmed/signal breakdown
    test_cli_e2e.py                # EXTENDED: schema-dump subprocess test
    test_schema_dump.py            # NEW
  docs/
    spec-checklist.md              # NEW (process artifact, see §9)
    superpowers/specs/
      2026-05-28-token-leak-profiler-v2-design.md   # this file
```

## 4. Data Model Changes

### Finding gains `evidence_kind`

```python
EvidenceKind = Literal["confirmed", "signal"]

@dataclass
class Finding:
    location: str
    leaked_tokens: int
    confidence: Confidence
    suggestion: str
    evidence: dict = field(default_factory=dict)
    evidence_kind: EvidenceKind = "confirmed"   # NEW
```

Default `"confirmed"` keeps all v1 tests passing without modification — only `reasoning_overrun`'s ratio-only path explicitly sets `"signal"`.

### LeakReport gains breakdown properties

```python
@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int            # total (confirmed + signal)
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

`leaked_tokens` on the report stays as the analyzer's reported total (matches v1 — analyzers don't have to know about the split).

## 5. Analyzer Changes

### 5.1 Existing five analyzers (stale_context, redundant_restatement, tool_schema_bloat, verbose_tool_results, format_boilerplate)

All Finding constructions get one explicit field added: `evidence_kind="confirmed"`. No algorithm changes. All v1 tests stay green.

### 5.2 reasoning_overrun branching

```python
# Inside the loop, at finding construction (current behavior already nearly here):
if dup_tokens > 0:
    evidence_kind = "confirmed"   # measured duplicate-sentence pairs in visible thinking
    # confidence stays "mid" (or "high" — current logic preserved)
else:
    evidence_kind = "signal"      # ratio-only; thinking content was hidden/empty
    confidence = "low"            # already applied in commit e0d0083
findings.append(Finding(..., evidence_kind=evidence_kind, confidence=confidence))
```

This formalizes the e0d0083 fix and surfaces it through the new field.

### 5.3 cache_miss_penalty (new)

**Bucket:** `cache_creation`.
**Evidence kind:** `confirmed` — `usage.cache_creation_input_tokens` is measured, not estimated.

**Algorithm:**
1. Iterate assistant turns. For each, extract `usage.cache_creation_tokens`.
2. Skip turn 0 of the session and any turn where `cache_creation_tokens == 0`.
3. Let `affected_turns` = the filtered set. If `len(affected_turns) < min_recreation_turns` (default 3) OR mean cache_creation across them < `min_avg_creation_tokens` (default 1000), return an empty `LeakReport` (no finding).
4. Otherwise pattern is confirmed. Leaked tokens = sum of `cache_creation_tokens` over `affected_turns` only (turn 0's cache build is excluded by step 2, and unaffected turns contribute zero anyway). Bucket is `cache_creation`.
5. Emit a single Finding at `location = "session"` summarizing the pattern. Evidence dict includes `affected_turn_count`, `mean_creation_tokens`, `total_creation_tokens`.

**Suggestion:** "N turns recreated cache (avg M tok each). Likely cause: dynamic content at context tail. Check for timestamps, counters, or session-meta appended after stable system prompt."

**Why this measurement is "confirmed" but the leak isn't always avoidable:**
`cache_creation_tokens` is real billing data. Whether the user *can* eliminate it depends on workflow constraints. The Finding suggestion frames it as a diagnostic, not a guaranteed savings, and `confidence` defaults to `"mid"` (high if mean creation tokens > 5000).

## 6. CLI Changes

```
tlp analyze <path> [options]              # unchanged from v1
tlp schema-dump <path> [--format text|json]   # NEW
```

`tlp` (no subcommand) → typer help, exits 0.

### `tlp schema-dump` implementation
- Re-uses the parser's first-pass event collection but doesn't build the full `ParsedTrace` — we want raw event/type counts before normalization.
- `tlp/schema/dump.py` exports `dump(path: Path) -> SchemaReport` (a small dataclass) and `render_text(report)` / `render_json(report)`.
- JSON output is a flat dict mirroring the text fields for downstream tooling.

### `cli.py` housekeeping
Remove the `_noop` hidden command from v1 Task 16. With two real `@app.command()` registrations typer's multi-command routing works natively.

## 7. Reporter Changes

### table.py
- The current v1.1 output prints two summary lines ("Estimated total leak" + "Effective leak (cache-adjusted)"). Replace these with three:
  ```
  Confirmed leak:     X tok / $Y      (content-based measurement)
  Attention signals:  X tok / $Y      (high thinking-ratio etc., not proven waste)
  Effective leak (cache-adjusted):  ~$Z
  ```
  The "Estimated total leak (upper bound — fresh input rate)" line is dropped; it was misleading because it mixed confirmed and signal under one number.
- Lever summary table replaces `tokens` column with two: `confirmed` and `signal`.
- Per-lever findings table adds `kind` column (`CONF` / `SIG`).

### json_renderer.py
- Top-level keys:
  - Add `confirmed_leak_cost_usd`, `signal_attention_cost_usd`.
  - Rename `total_effective_leak_cost_usd` → `effective_leak_cost_usd` (same number, cleaner name).
- Each report adds `confirmed_tokens`, `signal_tokens`.
- Each finding adds `evidence_kind`.

Backward compat: v1 consumers reading `total_effective_leak_cost_usd` break. v1 has no external consumers (no published version), so this is the cleanup moment.

## 8. Config Changes

`tlp/config/defaults.yaml` adds:
```yaml
cache_miss_penalty:
  min_recreation_turns: 3
  min_avg_creation_tokens: 1000
```

Everything else unchanged.

## 9. Spec Checklist Document

`docs/spec-checklist.md` — a process artifact (not code), enforced by reference.

Content outline:

1. **Before writing data model**: run `tlp schema-dump` against three representative real transcripts. Attach the outputs to the spec's §2 Inputs.
2. **Surface assumptions explicitly**: any event type or content block type observed should be either handled or explicitly skipped with rationale.
3. **Cache modeling is v1-critical**: any analyzer reporting input-bucket tokens must specify how cache_read/cache_creation are treated in cost math (blended rate? excluded? both?).
4. **Test fixture must mirror real schema variation**: at minimum one fixture with multi-event message (streaming split), one with redacted thinking, one with cache_creation pattern.
5. **Real-transcript sanity is not "turn count and no traceback"**: it's "every event type accounted for; cost math reconciles within 5% of human-confirmed Anthropic console figure for at least one session."

This document gets cited from the next spec's §2 ("Inputs follow the checklist at docs/spec-checklist.md").

## 10. Error Handling

Unchanged from v1. `cache_miss_penalty` follows existing patterns:
- Missing or zero `usage` → produces empty finding list, not an error.
- Pattern below threshold → empty findings.

`tlp schema-dump`:
- File not found → exit 1.
- Malformed JSON lines → counted in `skipped events` section, not fatal.

## 11. Testing Strategy

### v1 regression
All 53 v1 tests must stay green. The `evidence_kind` default keeps Finding construction backward-compat. Reporter test updates re-anchor on the new field names.

### New tests
- **`test_finding_evidence_kind_default`** — Finding without explicit kind → `"confirmed"`.
- **`test_leak_report_breakdown_properties`** — `confirmed_tokens` + `signal_tokens` = `leaked_tokens` total.
- **`test_cache_miss_penalty_*`** (3 cases): positive (3+ turns cache_creation > threshold), negative (steady cache_read only), edge (1 large cache_creation turn → not a pattern).
- **`test_reasoning_overrun_confirmed_when_dup_pairs`** — visible-thinking fixture with duplicate sentence → finding has `evidence_kind="confirmed"`, `confidence="mid"`.
- **`test_reasoning_overrun_signal_when_redacted`** — extends existing redacted test → finding has `evidence_kind="signal"`, `confidence="low"`.
- **`test_reporter_json_breakdown_keys`** — `confirmed_leak_cost_usd` / `signal_attention_cost_usd` present at top level; per-report `confirmed_tokens` / `signal_tokens` present.
- **`test_reporter_table_two_summary_lines`** — table output contains "Confirmed leak:" and "Attention signals:" substrings.
- **`test_schema_dump_text_output`** — `tlp schema-dump <fixture>` subprocess returns 0 and stdout contains expected section headers.
- **`test_schema_dump_json_output`** — same with `--format json`, parses as dict with expected keys.
- **`test_cli_no_subcommand_shows_help`** — `tlp` alone returns 0, stdout has "analyze" and "schema-dump".

### New fixtures
- `tests/fixtures/synthetic/cache_miss_trace.jsonl` — 5 assistant turns each with `cache_creation_input_tokens > 1000`.
- (Optional) `tests/fixtures/synthetic/visible_thinking_trace.jsonl` — single assistant turn with non-empty `thinking` text containing repeated sentence; used to test confirmed-kind branch of reasoning_overrun.

### Coverage targets
Unchanged: analyzers ≥ 90%, parser ≥ 95%.

## 12. Dependencies & Runtime

No new runtime deps. typer multi-command is already supported by the pinned version.

## 13. Migration & Versioning

- Bump `tlp/__init__.py` `__version__` from `0.1.0` to `0.2.0`.
- JSON field rename (`total_effective_leak_cost_usd` → `effective_leak_cost_usd`) is a breaking change for any consumer; v1 had none, so safe to land in v0.2.0.
- v1 spec/plan files stay in place as historical record.

## 14. v3+ Backlog

Carried forward from v1 + new items from v2 brainstorming:

- `tlp aggregate <dir>` — multi-session aggregation (v2.1).
- OpenAI / Gemini provider adapters (v2.x).
- `unbounded_growth` lever — same-pattern message accumulation (v2.x).
- Embedding-based stale_context / redundant_restatement precision upgrade (v3).
- Savings simulation: apply suggestion, recompute total (v3).
- Markdown / HTML reports (v3).
- Live tap via Anthropic SDK middleware (out of scope unless distinct product).
- pyproject entry-points for external analyzer registration (v3).

## 15. Open Questions (decide during implementation)

- `cache_miss_penalty` per-turn vs session-level granularity — current spec is session-level with a single Finding. If real fixtures show actionable per-turn patterns (e.g., turn 7 specifically broke the cache), a follow-up PR can add per-turn Findings while keeping the session summary.
- Schema dump output verbosity — current spec keeps it terse. If multiple users hit the same parser surprise, dump format may want a `--verbose` flag with sample event excerpts.
