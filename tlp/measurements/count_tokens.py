"""Anthropic count_tokens wrapper for populating measurements.yaml."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Protocol

import yaml


class _ClientLike(Protocol):
    messages: Any


_BASELINE_MESSAGES = [{"role": "user", "content": "x"}]
_BASELINE_SYSTEM = ""


def count_tool_tokens(
    client: _ClientLike,
    *,
    model: str,
    tools: list[dict],
) -> dict[str, int]:
    """Return per-tool marginal token cost.

    Marginal = count(system, messages, [tool]) - count(system, messages, []).
    """
    if not tools:
        return {}

    baseline = client.messages.count_tokens(
        model=model,
        system=_BASELINE_SYSTEM,
        messages=_BASELINE_MESSAGES,
        tools=[],
    ).input_tokens

    result: dict[str, int] = {}
    for tool in tools:
        name = tool["name"]
        with_tool = client.messages.count_tokens(
            model=model,
            system=_BASELINE_SYSTEM,
            messages=_BASELINE_MESSAGES,
            tools=[tool],
        ).input_tokens
        result[name] = with_tool - baseline
    return result


def write_measurements(
    target: Path,
    tools: dict[str, int],
    *,
    model: str,
    merge: bool,
) -> None:
    """Write measurements to YAML.

    merge=True: preserve existing tool keys not in `tools`.
    merge=False: replace tools mapping wholesale.
    Always sets top-level `model` key.
    """
    existing_tools: dict[str, int] = {}
    if merge and target.exists():
        data = yaml.safe_load(target.read_text()) or {}
        existing_tools = dict(data.get("tools") or {})
    merged = {**existing_tools, **tools} if merge else dict(tools)
    payload = {"model": model, "tools": merged}
    target.write_text(yaml.safe_dump(payload, sort_keys=True))
