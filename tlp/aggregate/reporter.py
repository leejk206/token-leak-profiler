from __future__ import annotations
import json as _json
from dataclasses import asdict
from rich.console import Console
from rich.table import Table
from rich import box

from tlp.aggregate.types import AggregateReport


def render_table(report: AggregateReport, *, console: Console | None = None) -> None:
    console = console or Console()
    console.rule(f"[bold]Aggregate — {report.session_count} session(s)")

    if report.session_count == 0:
        console.print("[dim]no sessions matched[/dim]")
        return

    tab = Table(box=box.SIMPLE_HEAVY)
    tab.add_column("session", style="cyan", overflow="fold", no_wrap=False, min_width=12)
    tab.add_column("turns", justify="right")
    tab.add_column("cost ($)", justify="right")
    tab.add_column("leak ($)", justify="right")
    tab.add_column("leak %", justify="right")
    tab.add_column("dominant lever", overflow="fold")
    tab.add_column("outlier", justify="center")

    for s in report.sessions:
        outlier_marker = "[red]⚠ OUTLIER[/red]" if s.is_outlier else ""
        leak_pct = s.leak_ratio * 100
        tab.add_row(
            s.label,
            f"{s.turn_count:,}",
            f"{s.total_cost_usd:.4f}",
            f"{s.effective_leak_cost_usd:.4f}",
            f"{leak_pct:.1f}%",
            s.dominant_lever or "",
            outlier_marker,
        )
    console.print(tab)

    total_turns = sum(s.turn_count for s in report.sessions)
    leak_pct = (
        (report.total_effective_leak_usd / report.total_cost_usd * 100)
        if report.total_cost_usd > 0 else 0.0
    )
    console.print(
        f"[bold]Total:[/bold] {total_turns:,} turns / "
        f"${report.total_cost_usd:.4f} cost / "
        f"${report.total_effective_leak_usd:.4f} effective leak "
        f"({leak_pct:.1f}%)"
    )
    median_pct = report.median_leak_ratio * 100
    threshold_pct = report.outlier_threshold * 100
    console.print(
        f"[dim]Median session leak: {median_pct:.1f}%, "
        f"outlier threshold: {threshold_pct:.1f}%[/dim]"
    )


def render_json(report: AggregateReport) -> str:
    payload = {
        "session_count": report.session_count,
        "total_cost_usd": report.total_cost_usd,
        "total_effective_leak_usd": report.total_effective_leak_usd,
        "median_leak_ratio": report.median_leak_ratio,
        "outlier_threshold": report.outlier_threshold,
        "sessions": [
            {**asdict(s), "path": str(s.path)} for s in report.sessions
        ],
    }
    return _json.dumps(payload, ensure_ascii=False, indent=2)
