# tlp — Token Leak Profiler

Measure actionable LLM token costs in Claude Code sessions.

## Install (dev)

    uv sync --all-extras

## Usage

    uv run tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

Aggregate multiple sessions in a project directory:

    uv run tlp aggregate ~/.claude/projects/<slug>/

Common flags:

    --format {table,json}        default: table
    --output PATH                write JSON to file
    --analyzers a,b,c            run only these (default: all 10)
    --verify                     compare local tokenizer to anthropic API
    --min-confidence {low,mid,high}
    --strict                     abort on parser warnings

## Schema discovery

Before writing or updating a spec that depends on transcript shape, dump real
sessions first:

    uv run tlp schema-dump ~/.claude/projects/<slug>/<session>.jsonl

See `docs/spec-checklist.md` for the full pre-spec workflow.

## Levers (11)

v0.6.0 aligned to the [blog 6-lever taxonomy](https://leejk.vercel.app/notes/2026-05-21-token-frugality): **6/6 (full coverage)**.

### Confirmed leak (5) — actionable, direct prescription verified

| name | bucket | what it catches | prescription |
|---|---|---|---|
| format_boilerplate | output | preambles/closers repeated across turns | "no preamble" or stop sequence |
| cache_turnover_cost (recoverable) | cache_creation | TTL idle expiry (gap ≥ 300s) | reduce idle time |
| redundant_restatement | input | near-duplicate text blocks (jaccard ≥ 0.9) | move to system prompt |
| subagent_context_overdump | input | subagent dispatch prompt > 5k tok | narrow scope on next dispatch |
| mcp_server_overhead | input | activated MCP server with 0 calls this session | disable in settings (~/.claude/claude.json) |

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

## Tests

    uv run pytest

## License

MIT (see LICENSE).
