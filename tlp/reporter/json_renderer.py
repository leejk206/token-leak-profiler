from __future__ import annotations
import json
from dataclasses import asdict
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_json(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
) -> str:
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

    # Effective input rate blends fresh input + cache_read + cache_creation by token share.
    total_input_like = total_input + total_cache_read + total_cache_creation
    if total_input_like > 0:
        blended_input_rate = (
            trace.pricing.input_per_mtok * total_input
            + trace.pricing.cache_read_per_mtok * total_cache_read
            + trace.pricing.cache_creation_per_mtok * total_cache_creation
        ) / total_input_like
    else:
        blended_input_rate = trace.pricing.input_per_mtok

    rendered_reports = []
    total_effective_leak = 0.0
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        # Effective cost accounts for prompt caching — input-bucket leaks ride the
        # cache_read rate proportionally, output-bucket leaks are unchanged.
        if bucket == "input":
            effective_cost = r.leaked_tokens / 1_000_000 * blended_input_rate
        else:
            effective_cost = cost
        total_effective_leak += effective_cost
        rendered_reports.append({
            "analyzer": r.analyzer,
            "lever": r.lever.value,
            "usage_bucket": bucket,
            "leaked_tokens": r.leaked_tokens,
            "leaked_cost_usd": cost,
            "effective_cost_usd": effective_cost,
            "findings": [asdict(f) for f in r.findings],
            "error": r.error,
        })

    payload = {
        "session_id": trace.session_id,
        "turn_count": len(trace.turns),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_creation,
        "total_cost_usd": total_cost,
        "tokenizer": {"mode": tokenizer_mode, "verify_drift_pct": verify_drift_pct},
        "blended_input_rate_per_mtok": blended_input_rate,
        "total_effective_leak_cost_usd": total_effective_leak,
        "reports": rendered_reports,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
