from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich import box
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_table(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    findings_per_lever: int = 5,
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()

    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    total_cost = (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )

    console.rule(f"[bold]Token Leak Profile — session {trace.session_id}")
    console.print(
        f"turns: {len(trace.turns)}  ·  "
        f"input(fresh): {total_input:,}  ·  output: {total_output:,}  ·  "
        f"cost: ${total_cost:.4f}"
    )
    if total_cache_read or total_cache_creation:
        console.print(
            f"[dim]cache_read: {total_cache_read:,}  ·  "
            f"cache_creation: {total_cache_creation:,}[/dim]"
        )
    if verify_drift_pct is not None:
        console.print(f"[dim]tokenizer={tokenizer_mode}, verify drift {verify_drift_pct:+.1f}%[/dim]")

    # Top-line table
    summary = Table(box=box.SIMPLE_HEAVY, title="Leak by lever")
    summary.add_column("lever", style="cyan")
    summary.add_column("tokens", justify="right")
    summary.add_column("cost ($)", justify="right")
    summary.add_column("% of total", justify="right")
    total_leaked_tokens = 0
    total_leaked_cost = 0.0
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        total_leaked_tokens += r.leaked_tokens
        total_leaked_cost += cost
        pct = (r.leaked_tokens / max(total_input + total_output, 1)) * 100
        marker = " [red]ERR[/red]" if r.error else ""
        summary.add_row(
            r.lever.value + marker,
            f"{r.leaked_tokens:,}",
            f"{cost:.4f}",
            f"{pct:.1f}%",
        )
    console.print(summary)

    total_input_like = total_input + total_cache_read + total_cache_creation
    blended_input_rate = (
        (trace.pricing.input_per_mtok * total_input
         + trace.pricing.cache_read_per_mtok * total_cache_read
         + trace.pricing.cache_creation_per_mtok * total_cache_creation) / total_input_like
        if total_input_like > 0 else trace.pricing.input_per_mtok
    )
    effective_total = 0.0
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        if bucket == "input":
            effective_total += r.leaked_tokens / 1_000_000 * blended_input_rate
        else:
            effective_total += trace.pricing.cost(r.leaked_tokens, bucket)

    console.print(
        f"[bold]Estimated total leak:[/bold] "
        f"{total_leaked_tokens:,} tok / ${total_leaked_cost:.4f} "
        f"[dim](upper bound — fresh input rate, no cache discount)[/dim]"
    )
    console.print(
        f"[bold]Effective leak (cache-adjusted):[/bold] "
        f"~${effective_total:.4f} "
        f"[dim](blended input rate ${blended_input_rate:.2f}/Mtok)[/dim]"
    )

    # Findings per lever
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        if r.error:
            console.rule(f"[yellow]{r.lever.value} — analyzer error: {r.error}[/yellow]")
            continue
        if not r.findings:
            continue
        console.rule(f"[bold cyan]{r.lever.value}[/bold cyan]")
        ftab = Table(box=box.MINIMAL, show_header=True)
        ftab.add_column("location", style="dim", overflow="fold")
        ftab.add_column("tokens", justify="right")
        ftab.add_column("conf", justify="center")
        ftab.add_column("suggestion", overflow="fold")
        for f in r.findings[:findings_per_lever]:
            ftab.add_row(f.location, f"{f.leaked_tokens:,}", f.confidence, f.suggestion)
        console.print(ftab)
