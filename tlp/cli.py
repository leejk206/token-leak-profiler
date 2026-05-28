from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.reporter import render_table, render_json

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command(hidden=True)
def _noop() -> None:
    """Hidden command that forces typer into multi-command mode."""
    pass  # pragma: no cover


@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    analyzers: Optional[str] = typer.Option(None, "--analyzers", help="comma-separated subset"),
    verify: bool = typer.Option(False, "--verify", help="verify with anthropic count_tokens"),
    min_confidence: str = typer.Option("mid", "--min-confidence", help="low | mid | high"),
    strict: bool = typer.Option(False, "--strict", help="abort on parse errors"),
) -> None:
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("table", "json"):
        typer.echo(f"error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        pricing = load_pricing(pricing_path)
        trace = parse(path, pricing=pricing, strict=strict)
        config = load_defaults(config_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:  # internal
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
    bucket_map: dict[str, str] = {}
    for cls in selected:
        bucket_map[cls.name] = cls.usage_bucket
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            from tlp.types import LeakReport, LeverCategory
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
                error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        reports.append(r)

    drift_pct = None
    if verify:
        from tlp.tokenizer.verify import compute_drift_pct
        sample = [
            {"role": "user", "content": (b.text or "")}
            for t in trace.turns for b in t.blocks
            if t.role == "user" and b.kind == "text"
        ][:20]  # cap to avoid runaway
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


if __name__ == "__main__":
    app()
