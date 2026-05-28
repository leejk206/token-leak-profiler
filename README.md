# tlp — Token Leak Profiler

Classify wasted LLM tokens in Claude Code session transcripts by 7 leak levers
and get actionable suggestions for each leak.

## Install (dev)

    uv sync --all-extras

## Usage

    uv run tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

Aggregate multiple sessions in a project directory:

    uv run tlp aggregate ~/.claude/projects/<slug>/

Common flags:

    --format {table,json}        default: table
    --output PATH                write JSON to file
    --analyzers a,b,c            run only these (default: all 7)
    --verify                     compare local tokenizer to anthropic API
    --min-confidence {low,mid,high}
    --strict                     abort on parser warnings

## Schema discovery

Before writing or updating a spec that depends on transcript shape, dump real
sessions first:

    uv run tlp schema-dump ~/.claude/projects/<slug>/<session>.jsonl

See `docs/spec-checklist.md` for the full pre-spec workflow.

## Levers

v0.4.0 distinguishes **confirmed leak** (actionable, direct prescription verified) from **signal** (measurement without verified prescription — inspect before acting).

Confirmed leak은 처방 검증된 누수입니다. Signals는 측정값이며 사용자가 검토 후 판단합니다.

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

## Tests

    uv run pytest

## License

MIT (see LICENSE).
