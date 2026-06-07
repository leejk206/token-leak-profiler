from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.reporter import render_table, render_json
from tlp.types import UsageBucket
from tlp.schema.dump import dump as schema_dump_run, render_text as schema_render_text, render_json as schema_render_json
from tlp.aggregate import aggregate as aggregate_run, render_table as agg_render_table, render_json as agg_render_json

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    analyzers: Optional[str] = typer.Option(None, "--analyzers", help="comma-separated subset"),
    verify: bool = typer.Option(False, "--verify", help="verify with anthropic count_tokens"),
    min_confidence: str = typer.Option("low", "--min-confidence", help="low | mid | high"),
    strict: bool = typer.Option(False, "--strict", help="abort on parse errors"),
) -> None:
    """Analyze a Claude Code transcript for token leaks across 12 analyzers."""
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("table", "json"):
        typer.echo("error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        pricing = load_pricing(pricing_path)
        trace = parse(path, pricing=pricing, strict=strict)
        config = load_defaults(config_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    selected = registry.all()
    if analyzers:
        wanted = {n.strip() for n in analyzers.split(",")}
        selected = [a for a in selected if a.name in wanted]
        if not selected:
            typer.echo(f"error: no matching analyzers in {analyzers!r}", err=True)
            raise typer.Exit(code=1)

    conf_rank = {"low": 0, "mid": 1, "high": 2}
    min_rank = conf_rank.get(min_confidence, 1)

    reports = []
    bucket_map: dict[str, UsageBucket] = {}
    for cls in selected:
        bucket_map[cls.name] = cls.usage_bucket
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            from tlp.types import LeakReport
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
                error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        # Recompute leaked_tokens after filter so summary matches displayed findings
        r.leaked_tokens = sum(f.leaked_tokens for f in r.findings)
        reports.append(r)

    drift_pct = None
    if verify:
        from tlp.tokenizer.verify import compute_drift_pct
        sample = [
            {"role": "user", "content": (b.text or "")}
            for t in trace.turns for b in t.blocks
            if t.role == "user" and b.kind == "text"
        ][:20]
        local_total = sum(t.usage.input_tokens for t in trace.turns if t.usage)
        drift_pct = compute_drift_pct(local_total, sample)

    findings_per_lever = config.get("report", {}).get("findings_per_lever", 5)

    if format == "json":
        out = render_json(
            trace, reports, bucket_map=bucket_map,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
        )
        if output:
            output.write_text(out)
        else:
            sys.stdout.write(out + "\n")
    else:
        render_table(
            trace, reports, bucket_map=bucket_map,
            findings_per_lever=findings_per_lever,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
            console=Console(force_terminal=False if not sys.stdout.isatty() else None),
        )


@app.command(name="schema-dump")
def schema_dump(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("text", "--format", help="text | json"),
) -> None:
    """Dump structural schema of a transcript (event types, block types, etc.)."""
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("text", "json"):
        typer.echo("error: --format must be 'text' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        report = schema_dump_run(path)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    if format == "json":
        sys.stdout.write(schema_render_json(report) + "\n")
    else:
        sys.stdout.write(schema_render_text(report) + "\n")


@app.command(name="aggregate")
def aggregate(
    paths: list[Path] = typer.Argument(..., help="One or more .jsonl files or directories"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    outlier_multiplier: Optional[float] = typer.Option(
        None, "--outlier-multiplier",
        help="override aggregate.outlier_multiplier (default 2.0)",
    ),
    min_confidence: str = typer.Option("low", "--min-confidence", help="low | mid | high"),
    include_subagents: bool = typer.Option(
        False, "--include-subagents",
        help="Include subagent transcripts (subagents/ dirs)",
    ),
) -> None:
    """Aggregate multiple session transcripts with median-based outlier flagging."""
    if format not in ("table", "json"):
        typer.echo("error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)
    for p in paths:
        if not p.exists():
            typer.echo(f"error: file not found: {p}", err=True)
            raise typer.Exit(code=1)

    try:
        report = aggregate_run(
            paths,
            config_path=config_path,
            pricing_path=pricing_path,
            outlier_multiplier=outlier_multiplier,
            min_confidence=min_confidence,
            include_subagents=include_subagents,
        )
    except FileNotFoundError as e:
        typer.echo(f"error: file not found: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    if report.session_count == 0:
        typer.echo("no sessions matched")
        return

    if format == "json":
        out = agg_render_json(report)
        if output:
            output.write_text(out)
        else:
            sys.stdout.write(out + "\n")
    else:
        agg_render_table(
            report,
            console=Console(force_terminal=False if not sys.stdout.isatty() else None),
        )


@app.command("count-tokens")
def count_tokens(
    tools: Path = typer.Option(
        ..., "--tools", "-t",
        exists=True,
        help="JSON file of Anthropic-format tool definitions",
    ),
    output: Path = typer.Option(
        Path(__file__).parent / "config" / "measurements.yaml",
        "--output", "-o",
        help="Target measurements.yaml (default: tlp/config/measurements.yaml)",
    ),
    model: str = typer.Option(
        "claude-opus-4-7", "--model",
        help="Anthropic model id used by count_tokens API",
    ),
    merge: bool = typer.Option(
        False, "--merge",
        help="Merge into existing measurements (default: overwrite)",
    ),
) -> None:
    """Populate measurements.yaml via Anthropic count_tokens API."""
    import json as _json
    import os as _os

    if not _os.environ.get("ANTHROPIC_API_KEY"):
        typer.echo("ANTHROPIC_API_KEY not set; required for tlp count-tokens", err=True)
        raise typer.Exit(1)

    try:
        import anthropic
    except ImportError:
        typer.echo("anthropic SDK not installed; uv sync --extra verify", err=True)
        raise typer.Exit(1)

    try:
        tool_defs = _json.loads(tools.read_text())
    except _json.JSONDecodeError as e:
        typer.echo(f"Malformed tools JSON: {e}", err=True)
        raise typer.Exit(1)

    if not isinstance(tool_defs, list):
        typer.echo("tools.json must be a list of tool definitions", err=True)
        raise typer.Exit(1)

    from tlp.measurements import count_tool_tokens, write_measurements

    client = anthropic.Anthropic()
    measurements = count_tool_tokens(client, model=model, tools=tool_defs)
    write_measurements(output, measurements, model=model, merge=merge)

    typer.echo(f"Wrote {len(measurements)} tool measurements to {output}")
    for name, n in sorted(measurements.items()):
        typer.echo(f"  {name}: {n}")


if __name__ == "__main__":
    app()
