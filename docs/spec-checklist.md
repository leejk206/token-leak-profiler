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
