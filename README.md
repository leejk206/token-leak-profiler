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

v0.6.1 aligned to the [blog 6-lever taxonomy](https://leejk.vercel.app/notes/2026-05-21-token-frugality): **6/6 (per-session retrospective scope; blog originally described per-turn dynamic activation — see scope note)**.

> v0.6.1 introduces a 3-tier evidence model:
> - **Confirmed**: measurement + actionable prescription
> - **Estimated**: heuristic + actionable prescription (inspect evidence for assumptions)
> - **Signal**: measurement without verified prescription

### Confirmed leak (4) — measurement + actionable prescription

| name | bucket | what it catches | prescription |
|---|---|---|---|
| format_boilerplate | output | preambles/closers repeated across turns | "no preamble" or stop sequence |
| cache_turnover_cost (recoverable) | cache_creation | TTL idle expiry (gap ≥ 300s) | reduce idle time |
| redundant_restatement | input | near-duplicate text blocks (jaccard ≥ 0.9) | move to system prompt |
| subagent_context_overdump | input | subagent dispatch prompt > 5k tok | narrow scope on next dispatch |

### Estimated leak (1) — heuristic + actionable prescription (inspect evidence for assumptions)

| name | bucket | what it catches | prescription |
|---|---|---|---|
| mcp_server_overhead | input | activated MCP server with 0 calls this session (200 tok/tool heuristic, range 100-1000) | disable in settings (~/.claude/claude.json) |

**MCP partial-use sub-case** (v0.7.0): a server with <30% of its tools used flags the unused subset (location format: `mcp_server[name].partial(unused/total)`). Catches Council Red Team Scenario B: servers like Bash with 80 commands where only 1 is ever called.

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

## Measurements (optional)

Create `tlp/config/measurements.yaml` to supply empirically-measured tool token counts (e.g., from Anthropic's `count_tokens` API). When all tools of an unused MCP server are measured, `mcp_server_overhead` Findings promote from `estimated` → `confirmed`.

Example:

```yaml
tools:
  mcp__pal__chat: 312
  mcp__pal__thinkdeep: 298
```

Pass via CLI: `uv run tlp analyze --measurements tlp/config/measurements.yaml <session.jsonl>`

## Tests

    uv run pytest

## Contributing

Install pre-commit hooks before your first commit:

```bash
uv sync --group dev
uv run pre-commit install
```

The pre-commit gate enforces:
- `tests/test_rules_self_application.py` (rules 5/6 — runs only when analyzer code changes)
- `ruff check`

## License

MIT (see LICENSE).
