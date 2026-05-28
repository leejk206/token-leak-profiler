# Token Leak Profiler v0.5.0 — Design Spec

- **Date**: 2026-05-29
- **Owner**: ljk9121
- **Status**: Approved (brainstorming) → ready for implementation plan
- **Builds on**: [v0.4 design](2026-05-29-token-leak-profiler-v0.4-design.md)
- **Spec-checklist applied**: rules 1, 2, 3, 5 self-applied
- **External source**: aligns to [blog 6-lever taxonomy](https://leejk.vercel.app/notes/2026-05-21-token-frugality)

## 1. Goal

Add 4 new analyzers aligned to the blog's 6-lever workflow taxonomy. Reject 1 (model_choice) after field-level discovery proved it unmeasurable in Claude Code transcripts. Bring blog lever coverage from 1/6 (v0.4.0) to 5/6.

## 2. Inputs & Schema Discovery Evidence

### 2.1 Field-level discovery results (rule 1 applied)

Three real sessions inspected before data model design:

**`model` field distribution (af0b624f session, 773 turns):**
```
{'claude-opus-4-7': 773}
```
**Single model per session.** Turn-by-turn model classification is structurally inapplicable — Claude Code sets model session-wide, not per turn. → `model_choice_inefficiency` rejected (rule 5 violation: no actionable user prescription from a per-turn measurement).

**Subagent transcript structure:**
```
{"parentUuid":null,"isSidechain":true,"promptId":"...","agentId":"...",
 "type":"user","message":{"role":"user","content":"You are implementing Task 5..."}}
```
First event of every subagent transcript carries the dispatch prompt verbatim. **Measurable directly** — first user message tokens.

**User message length distribution (af0b624f):**
```
Total str-content user messages: 44
{'<20': 26 (61%), '20-100': 16 (37%), '100-500': 0, '500+': 2}
```
Confirms short-message-run pattern exists. `roundtrip_inflation` measurable.

### 2.2 Lever decisions (rule 5 applied)

| Candidate | Measurable? | 1:1 prescription? | Decision |
|---|---|---|---|
| `subagent_context_overdump` | ✅ subagent first user msg tokens | ✅ "narrow scope on next dispatch" | **confirmed** |
| `system_prompt_audit` | ✅ stable_prefix_tokens (existing) | ⚠ "disable unused skills" (general) | **signal** |
| `roundtrip_inflation` | ✅ short-msg run | ⚠ "use Plan/AskUser" (Claude's choice) | **signal** |
| `tool_result_repetition` (verbose split) | ✅ tool_name + input dict equality | ⚠ "cache mentally" (Claude's choice) | **signal** |
| `model_choice_inefficiency` | ❌ single model per session | ❌ no per-turn prescription | **reject** |

## 3. Architecture

Unchanged at top level: Registry + ParsedTrace. 4 new analyzer files. 1 helper extraction from cache_turnover_cost (stable_prefix calc) for reuse.

Subagent transcripts (`subagents/` subdir) currently filtered out in v0.3 `expand_paths`. v0.5 adds `--include-subagents` CLI flag for aggregate; the new `subagent_context_overdump` analyzer runs only on transcripts where `trace.is_subagent` is True (new field).

```
tlp/
  types.py                            # MODIFY: 4 enum values + ParsedTrace.is_subagent
  analyzers/
    __init__.py                       # MODIFY: 4 imports
    subagent_context_overdump.py      # NEW
    system_prompt_audit.py            # NEW
    roundtrip_inflation.py            # NEW
    tool_result_repetition.py         # NEW
    cache_turnover_cost.py            # MODIFY: extract stable_prefix helper
    _helpers.py                       # NEW (shared stable_prefix calc)
  aggregate/
    run.py                            # MODIFY: subagent_paths option
  cli.py                              # MODIFY: aggregate --include-subagents
  parser/
    claude_code.py                    # MODIFY: detect isSidechain → trace.is_subagent
  config/
    defaults.yaml                     # MODIFY: 4 new threshold blocks
tests/
  fixtures/synthetic/
    subagent_overdump_trace.jsonl     # NEW
    system_prompt_audit_trace.jsonl   # NEW
    roundtrip_inflation_trace.jsonl   # NEW
    tool_repeat_trace.jsonl           # NEW
  test_analyzers/
    test_subagent_context_overdump.py # NEW
    test_system_prompt_audit.py       # NEW
    test_roundtrip_inflation.py       # NEW
    test_tool_result_repetition.py    # NEW
  test_types.py                       # MODIFY
  test_cli_e2e.py                     # MODIFY (10 analyzers + flag)
  test_aggregate.py                   # EXTEND
docs/superpowers/
  specs/2026-05-29-token-leak-profiler-v0.5-design.md  # this file
```

## 4. Data Model Changes

### 4.1 `LeverCategory` 4 additions

```python
class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"
    CACHE_TURNOVER_COST = "cache_turnover_cost"
    SUBAGENT_CONTEXT_OVERDUMP = "subagent_context_overdump"   # NEW
    SYSTEM_PROMPT_AUDIT = "system_prompt_audit"               # NEW
    ROUNDTRIP_INFLATION = "roundtrip_inflation"               # NEW
    TOOL_RESULT_REPETITION = "tool_result_repetition"         # NEW
```

### 4.2 `ParsedTrace.is_subagent`

```python
@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable
    label: str | None = None
    is_subagent: bool = False          # NEW
```

Parser sets `is_subagent=True` if any first-pass event has `isSidechain=True` OR `agentId` field present.

## 5. Analyzer Specs

### 5.1 `subagent_context_overdump` (confirmed)

**Bucket:** `input` (the prompt sent to subagent counts as input tokens for that subagent's first call).

**Algorithm:**
1. If `not trace.is_subagent`, return empty report.
2. Find first turn with `role="user"`. If none, return empty.
3. Extract text-block tokens of first user turn → `first_prompt_tokens`.
4. If `first_prompt_tokens < min_subagent_prompt_tokens` (config, default 5000): return empty.
5. `leaked_tokens = first_prompt_tokens - baseline` (config `baseline_subagent_prompt_tokens`, default 1000).
6. Emit single Finding at `location="subagent_prompt"`.

**Suggestion:** `"Subagent dispatch prompt is {first_prompt_tokens} tok (recommended baseline: {baseline} tok). Narrow the scope on next dispatch — pass only the specific context needed for the task."`

**Evidence:** `{first_prompt_tokens, baseline, agent_id_if_available}`.

**Evidence kind:** `confirmed`. **Confidence:** "high" if first_prompt_tokens > 20000, "mid" else.

**Rule 5 justification:** User can directly edit the prompt argument to Agent tool on next dispatch.

### 5.2 `system_prompt_audit` (signal)

**Bucket:** `input`.

**Algorithm:**
1. If `trace.is_subagent`, return empty (only for parent sessions).
2. Reuse `cache_turnover_cost`'s stable_prefix calc (extracted to `_helpers.py`): mean of `actual_cr` values at invalidation events, if std-dev < 1% of mean. If no invalidation events, return empty (can't estimate).
3. If `stable_prefix_tokens < min_system_prompt_tokens` (config, default 15000), return empty.
4. `leaked_tokens = stable_prefix_tokens - baseline` (config `baseline_system_prompt_tokens`, default 10000).
5. Emit single Finding at `location="system_prompt"`.

**Suggestion:** `"Stable system-prompt prefix estimated at {stable_prefix_tokens} tok (baseline: ~{baseline} tok). Skills, plugins, or MCP servers loaded but unused contribute. Inspect /config to disable unused skills."`

**Evidence:** `{stable_prefix_tokens, baseline}`.

**Evidence kind:** `signal`. **Confidence:** `low`.

**Rule 5 justification (why signal not confirmed):** User can disable skills/MCP but the tool cannot point at *which* skills are unused. Generic prescription.

### 5.3 `roundtrip_inflation` (signal)

**Bucket:** `input`.

**Algorithm:**
1. Iterate turns. For each user turn with text-content block where `len(text) < short_threshold` (config `short_user_msg_chars`, default 20), mark as "short".
2. Find runs of consecutive short user turns of length ≥ `min_short_run` (config, default 3).
3. For each qualifying run: `leaked_tokens = (run_length - 1) × estimated_assistant_response_tokens` (config, default 500).
4. Emit Finding per run, `location="turn[start..end]"`.

**Suggestion:** `"{run_length} consecutive short user messages (avg < {short_threshold} chars). Could have been bundled into one Plan-mode session or single AskUserQuestion."`

**Evidence:** `{run_length, start_turn, end_turn, avg_user_msg_chars}`.

**Evidence kind:** `signal`. **Confidence:** `low`.

### 5.4 `tool_result_repetition` (signal)

**Bucket:** `input` (repeated tool result tokens re-enter input on next turn via conversation history).

**Algorithm:**
1. Collect `(tool_name, tool_input_canonical)` pairs from each tool_use block. `tool_input_canonical` = JSON-serialized with sorted keys.
2. Group by pair; if group size ≥ `min_repeat` (config, default 2):
   - Find each tool_use's matching tool_result (same `tool_use_id`).
   - `leaked_tokens = (group_size - 1) × sum(matching_tool_result_tokens)`.
3. Emit single Finding per (tool_name, input) group at `location="tool[{name}].repeat({count})"`.

**Suggestion:** `"Tool '{tool_name}' called {count} times with identical input. Re-using the prior result instead of re-calling could save {leaked_tokens} tok."`

**Evidence:** `{tool_name, repeat_count, sample_input_keys, tool_result_tokens_per_call}`.

**Evidence kind:** `signal`. **Confidence:** `low`.

### 5.5 `verbose_tool_results` stays unchanged

The existing low-citation-ratio analyzer remains a separate lever (signal, v0.4.0). `tool_result_repetition` is a *different* signal — both can fire on the same session.

## 6. Aggregate Changes

`expand_paths` gains optional inclusion. New parameter:

```python
def expand_paths(paths: list[Path], *, include_subagents: bool = False) -> list[Path]:
    ...
    if p.is_dir():
        for jsonl in sorted(p.rglob("*.jsonl")):
            if "subagents" in jsonl.parts and not include_subagents:
                continue
            out.append(jsonl)
```

`aggregate()` signature adds matching kwarg. CLI adds `--include-subagents` boolean flag (default False — backward-compat).

When subagents included, `SessionRow` distinguishes them by label prefix `[sub] <agent_id_short>`.

## 7. CLI Changes

```
tlp aggregate <path>... [options] [--include-subagents]
```

Other commands unchanged.

## 8. Config Changes

`tlp/config/defaults.yaml` adds:

```yaml
subagent_context_overdump:
  min_subagent_prompt_tokens: 5000
  baseline_subagent_prompt_tokens: 1000
system_prompt_audit:
  min_system_prompt_tokens: 15000
  baseline_system_prompt_tokens: 10000
roundtrip_inflation:
  short_user_msg_chars: 20
  min_short_run: 3
  estimated_assistant_response_tokens: 500
tool_result_repetition:
  min_repeat: 2
```

## 9. Reporter Changes

Existing rich table and JSON renderer accept new lever names transparently (registry is dynamic). No code changes required.

README update: lever catalog 6 → 10 with confirmed (4) vs signal (6) breakdown.

## 10. Error Handling

- subagent analyzer on non-subagent trace → empty report (no error).
- system_prompt_audit when stable_prefix can't be estimated (no invalidation events) → empty report.
- Other analyzers follow v0.4 conventions.

## 11. Testing Strategy

### v0.4.0 regression
117 tests stay green. Test files affected by new enum values:
- `test_types.py` enum set update (6 → 10 lever values)
- `test_cli_e2e.py` analyzer name set update (6 → 10), report count `len(data["reports"]) == 6 → 10`

### New per-analyzer tests (each ≥ 3)
- positive case (fixture triggers Finding)
- negative case (no Finding when below threshold)
- edge case (e.g. empty trace, single turn)

### Aggregate test
- `--include-subagents` flag inclusion verified
- subagent rows labeled distinctly

### Fixtures
- `subagent_overdump_trace.jsonl`: single-event subagent with 8k-token first prompt (above 5k threshold)
- `system_prompt_audit_trace.jsonl`: traces with multiple cache invalidations clustering at 17k stable prefix (above 15k threshold)
- `roundtrip_inflation_trace.jsonl`: 5 consecutive short user messages
- `tool_repeat_trace.jsonl`: same Read tool with same path called 3 times

## 12. Dependencies & Runtime

No new dependencies. All analyzers use stdlib + existing modules.

## 13. Migration & Versioning

- `tlp/__init__.py` `__version__ = "0.5.0"`
- `pyproject.toml` `version = "0.5.0"` (sync — v0.2 lesson)
- README:
  - Tagline: "Classify wasted LLM tokens" → "Measure actionable LLM token costs in Claude Code sessions"
  - Lever catalog updated 6 → 10
- Backward compat:
  - LeverCategory enum extension only adds values (existing consumers safe)
  - Aggregate `--include-subagents` defaults False (existing behavior preserved)

## 14. v0.6+ Backlog

- MCP server activation detection (`deferred_tools_delta` event analysis)
- Cross-session pattern detection (lever common to N% of sessions)
- Time-series view
- Markdown / HTML reports
- Provider adapters (OpenAI/Gemini)
- Simulation: apply suggestion, recompute totals
- Identity reframe: deeper rename if `tlp` package name proves confusing (CLI tagline already addressed in v0.5)
- model_usage_audit revisited if Claude Code introduces per-turn model selection
- subagent_context_overdump promotion from text-only first prompt to parent-side context dump measurement

## 15. Open Questions

- `roundtrip_inflation`'s `estimated_assistant_response_tokens` default 500 — calibrate against real data in implementation. If avg short-msg-run assistant response is materially different from 500, adjust default.
- `system_prompt_audit` requires `cache_turnover_cost` invalidation events to estimate stable prefix. Sessions with zero invalidations cannot be audited (returns empty). Acceptable for v0.5 — note in suggestion.
- `tool_result_repetition` canonical input form via `json.dumps(..., sort_keys=True)`. If tool_input contains unhashable types or non-deterministic ordering, this is good enough for current Anthropic API tool schemas. Verify on real fixtures.
