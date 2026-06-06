"""Verify-mode wrapper around anthropic.messages.count_tokens.

Network/API key failures are caught and reported as None drift so the CLI can
continue with local-only results.
"""
from __future__ import annotations


def compute_drift_pct(
    local_total: int,
    sample_messages: list[dict],
    *,
    model: str = "claude-sonnet-4-5",
) -> float | None:
    if local_total == 0:
        return 0.0
    try:
        remote = _count_via_anthropic(sample_messages, model=model)
    except Exception:
        return None
    return (remote - local_total) / local_total * 100.0


def _count_via_anthropic(messages: list[dict], *, model: str) -> int:
    from anthropic import Anthropic  # imported lazily so it stays optional
    client = Anthropic()
    resp = client.messages.count_tokens(model=model, messages=messages)  # type: ignore[arg-type]
    return int(resp.input_tokens)
