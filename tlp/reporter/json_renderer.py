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

    rendered_reports = []
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        rendered_reports.append({
            "analyzer": r.analyzer,
            "lever": r.lever.value,
            "usage_bucket": bucket,
            "leaked_tokens": r.leaked_tokens,
            "leaked_cost_usd": cost,
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
        "reports": rendered_reports,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
