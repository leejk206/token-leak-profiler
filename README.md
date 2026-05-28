# tlp — Token Leak Profiler

Classify wasted LLM tokens in Claude Code session transcripts by 6 leak levers
and get actionable suggestions for each leak.

## Install (dev)

    uv sync --all-extras

## Usage

    uv run tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

Common flags:

    --format {table,json}        default: table
    --output PATH                write JSON to file
    --analyzers a,b,c            run only these (default: all 6)
    --verify                     compare local tokenizer to anthropic API
    --min-confidence {low,mid,high}
    --strict                     abort on parser warnings

## Levers

| name | bucket | what it catches |
|---|---|---|
| stale_context | input | message blocks unreferenced for N turns |
| redundant_restatement | input | near-duplicate text blocks (MinHash 5-gram) |
| tool_schema_bloat | input | tool defs that are never called |
| verbose_tool_results | input | tool output that's mostly never cited |
| reasoning_overrun | output | thinking >> answer + duplicate sentences |
| format_boilerplate | output | preambles/closers repeated across turns |

## Tests

    uv run pytest

## License

MIT (see LICENSE).
