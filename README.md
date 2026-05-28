# tlp — Token Leak Profiler

Classify wasted LLM tokens in Claude Code session transcripts by 6 leak levers
(stale context, redundant restatement, tool schema bloat, verbose tool results,
reasoning overrun, format boilerplate).

## Usage

    tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

See `--help` for options.
