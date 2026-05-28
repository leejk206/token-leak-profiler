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

| name | bucket | what it catches |
|---|---|---|
| stale_context | input | message blocks unreferenced for N turns |
| redundant_restatement | input | near-duplicate text blocks (MinHash 5-gram) |
| tool_schema_bloat | input | tool defs that are never called |
| verbose_tool_results | input | tool output that's mostly never cited |
| reasoning_overrun | output | thinking >> productive + duplicate sentences |
| format_boilerplate | output | preambles/closers repeated across turns |
| cache_miss_penalty | cache_creation | repeated cache invalidation pattern |

## Tests

    uv run pytest

## License

MIT (see LICENSE).
