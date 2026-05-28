# Spec Checklist — tlp

A reference checklist for writing or updating specs in this project. Cited from
each spec's §2 Inputs section.

> **Lesson from v1–v0.3**: the same defect — "spec assumed input field shape
> without verifying" — recurred in four releases (`message.id` consecutive
> grouping, `tools_changed` skip, `tools` definition absence, `ai-title`
> wire format). Type-level discovery is not enough. Field-level inspection
> of one raw event per relevant type is mandatory.

## Before writing data model

1. Run `tlp schema-dump <transcript> --format json` against at least **three
   representative real sessions** from `~/.claude/projects/<slug>/`.
2. Attach the three outputs to the spec's §2 Inputs section.
3. Skim each dump and answer: are there any event types or content block types
   that are not already handled, explicitly skipped, or accounted for in the
   data model? If yes, decide handling before writing model.
4. **For every event type the spec will newly parse**, copy the
   `skipped event field samples:` line from `tlp schema-dump` output and
   inspect the listed keys. Write the parser against the actual field names
   (e.g., real ai-title events have a top-level `aiTitle` field, not a
   `message.content` wrapper — type counts alone don't reveal this, only the
   field listing does). Type counts are necessary but not sufficient for
   parser design; field listings are mandatory.

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

## Rule: "X > 0 = leak" is not enough — verify user-recoverability

(Added v0.3.3 after the 6th recurrence of this defect category.)

For any new metric or lever, the spec must answer THREE questions, not two:

1. **Is X = 0 the normal case?** (v1-v0.3.1 failures caught this stage)
2. **If X > 0 in the wild, does it indicate something abnormal?** (v0.3.2 fixed this for cache_miss_penalty)
3. **If X is abnormal AND > 0, can the user reduce it through their own actions?** (v0.3.2 missed this; council 2026-05-29 caught it for cache_turnover_cost)

If the answer to (3) is "no" or "only partially", the metric must be framed neutrally (e.g. "cost" not "leak"), and the spec must categorize sub-cases by recoverability so the user can distinguish what's actionable from what's API mechanics.

Reference: `docs/council/2026-05-29-cache-miss-penalty-deliberation.md`

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
