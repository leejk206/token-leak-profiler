from __future__ import annotations
import statistics
from pathlib import Path

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.aggregate.types import SessionRow, AggregateReport
from tlp.types import LeakReport


def expand_paths(paths: list[Path], *, include_subagents: bool = False) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)
        if p.is_dir():
            for jsonl in sorted(p.rglob("*.jsonl")):
                # Skip subagent sidechain transcripts; they share sessionId
                # with their parent and contaminate cost totals.
                if "subagents" in jsonl.parts and not include_subagents:
                    continue
                out.append(jsonl)
        elif p.is_file() and p.suffix == ".jsonl":
            out.append(p)
    return out


def aggregate(
    paths: list[Path],
    *,
    config_path: Path | None = None,
    pricing_path: Path | None = None,
    outlier_multiplier: float | None = None,
    min_confidence: str = "low",
    include_subagents: bool = False,
) -> AggregateReport:
    config = load_defaults(config_path)
    pricing = load_pricing(pricing_path)
    files = expand_paths(paths, include_subagents=include_subagents)

    multiplier = outlier_multiplier if outlier_multiplier is not None else float(
        config.get("aggregate", {}).get("outlier_multiplier", 2.0)
    )
    absolute_floor = float(config.get("aggregate", {}).get("outlier_absolute_floor", 0.1))

    rows_unflagged: list[SessionRow] = []
    for f in files:
        trace = parse(f, pricing=pricing)
        reports = _run_analyzers(trace, config, min_confidence)
        bucket_map = {r.analyzer: _bucket_for(r.analyzer) for r in reports}
        total_cost = _total_cost(trace)
        eff_leak = _effective_leak(trace, reports, bucket_map)
        leak_ratio = eff_leak / max(total_cost, 1e-9)
        positive = [r for r in reports if r.leaked_tokens > 0]
        dominant = max(positive, key=lambda r: r.leaked_tokens).analyzer if positive else None
        rows_unflagged.append(SessionRow(
            session_id=trace.session_id,
            label=trace.label or (trace.session_id if trace.session_id else "<unknown>"),
            path=f,
            turn_count=len(trace.turns),
            total_cost_usd=total_cost,
            effective_leak_cost_usd=eff_leak,
            leak_ratio=leak_ratio,
            dominant_lever=dominant,
            is_outlier=False,
        ))

    if not rows_unflagged:
        return AggregateReport(
            sessions=(), total_cost_usd=0.0, total_effective_leak_usd=0.0,
            median_leak_ratio=0.0, outlier_threshold=0.0, session_count=0,
        )

    median_ratio = statistics.median(r.leak_ratio for r in rows_unflagged)
    threshold = median_ratio * multiplier
    flagged: tuple[SessionRow, ...] = tuple(
        SessionRow(
            session_id=row.session_id, label=row.label, path=row.path,
            turn_count=row.turn_count, total_cost_usd=row.total_cost_usd,
            effective_leak_cost_usd=row.effective_leak_cost_usd,
            leak_ratio=row.leak_ratio, dominant_lever=row.dominant_lever,
            is_outlier=(
                len(rows_unflagged) > 1
                and (
                    (threshold > 0 and row.leak_ratio >= threshold)
                    or row.leak_ratio >= absolute_floor
                )
            ),
        )
        for row in rows_unflagged
    )

    return AggregateReport(
        sessions=flagged,
        total_cost_usd=sum(r.total_cost_usd for r in flagged),
        total_effective_leak_usd=sum(r.effective_leak_cost_usd for r in flagged),
        median_leak_ratio=median_ratio,
        outlier_threshold=threshold,
        session_count=len(flagged),
    )


# --- private helpers ---

def _run_analyzers(trace, config, min_confidence: str) -> list[LeakReport]:
    conf_rank = {"low": 0, "mid": 1, "high": 2}
    min_rank = conf_rank.get(min_confidence, 1)
    reports: list[LeakReport] = []
    for cls in registry.all():
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[], error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        r.leaked_tokens = sum(f.leaked_tokens for f in r.findings)
        reports.append(r)
    return reports


def _bucket_for(analyzer_name: str) -> str:
    cls = registry.get(analyzer_name)
    return cls.usage_bucket


def _total_cost(trace) -> float:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    return (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )


def _effective_leak(trace, reports: list[LeakReport], bucket_map: dict[str, str]) -> float:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    total_input_like = total_input + total_cache_read + total_cache_creation
    if total_input_like > 0:
        blended = (
            trace.pricing.input_per_mtok * total_input
            + trace.pricing.cache_read_per_mtok * total_cache_read
            + trace.pricing.cache_creation_per_mtok * total_cache_creation
        ) / total_input_like
    else:
        blended = trace.pricing.input_per_mtok
    eff = 0.0
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        if bucket == "input":
            eff += r.leaked_tokens / 1_000_000 * blended
        else:
            eff += trace.pricing.cost(r.leaked_tokens, bucket)
    return eff
