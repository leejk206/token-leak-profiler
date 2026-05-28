"""Schema discovery dump — surfaces transcript structure before parsing into ParsedTrace.

Use this as a spec-time tool: before designing or modifying an analyzer that
makes assumptions about the input shape, run `tlp schema-dump <transcript>`
on real sessions to verify those assumptions.
"""
from __future__ import annotations
import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class SchemaReport:
    session_id: str
    event_count: int
    event_types: dict[str, int] = field(default_factory=dict)
    assistant_block_types: dict[str, int] = field(default_factory=dict)
    user_block_types: dict[str, int] = field(default_factory=dict)
    unique_message_ids: int = 0
    max_message_id_repeat: int = 0
    mean_message_id_repeat: float = 0.0
    thinking_visible_count: int = 0
    thinking_redacted_count: int = 0
    tools_defined: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    skipped_event_types: dict[str, int] = field(default_factory=dict)


def dump(path: Path) -> SchemaReport:
    session_id = ""
    event_count = 0
    event_types: Counter[str] = Counter()
    assistant_blocks: Counter[str] = Counter()
    user_blocks: Counter[str] = Counter()
    message_id_counts: Counter[str] = Counter()
    thinking_visible = 0
    thinking_redacted = 0
    tools_defined: set[str] = set()
    tools_called: set[str] = set()
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    skipped: Counter[str] = Counter()
    seen_message_id_for_usage: set[str] = set()

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                skipped["__bad_json__"] += 1
                continue

            ev_type = event.get("type", "?")
            event_types[ev_type] += 1

            if not session_id:
                session_id = event.get("sessionId", "") or session_id

            msg = event.get("message")
            if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
                skipped[ev_type] += 1
                continue

            # Tool definitions
            for td in (event.get("tools") or []) + (msg.get("tools") or []):
                name = td.get("name")
                if name:
                    tools_defined.add(name)

            message_id = msg.get("id", "")
            if message_id:
                message_id_counts[message_id] += 1

            content = msg.get("content", [])
            if isinstance(content, str):
                if ev_type == "user":
                    user_blocks["text"] += 1
                else:
                    assistant_blocks["text"] += 1
            elif isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    ct = c.get("type", "?")
                    if ev_type == "user":
                        user_blocks[ct] += 1
                    else:
                        assistant_blocks[ct] += 1
                        if ct == "thinking":
                            if c.get("thinking"):
                                thinking_visible += 1
                            elif c.get("signature"):
                                thinking_redacted += 1
                            else:
                                thinking_redacted += 1
                        elif ct == "tool_use" and c.get("name"):
                            tools_called.add(c["name"])

            # Sum usage once per message.id to avoid streaming-split double count
            usage = msg.get("usage")
            if ev_type == "assistant" and isinstance(usage, dict) and message_id and message_id not in seen_message_id_for_usage:
                seen_message_id_for_usage.add(message_id)
                for k in usage_totals.keys():
                    val = usage.get(k, 0) or 0
                    try:
                        usage_totals[k] += int(val)
                    except (TypeError, ValueError):
                        pass
            elif ev_type == "assistant" and isinstance(usage, dict) and not message_id:
                # No message.id — assume single-event message, count once
                for k in usage_totals.keys():
                    val = usage.get(k, 0) or 0
                    try:
                        usage_totals[k] += int(val)
                    except (TypeError, ValueError):
                        pass

    if message_id_counts:
        unique_message_ids = len(message_id_counts)
        max_repeat = max(message_id_counts.values())
        mean_repeat = sum(message_id_counts.values()) / unique_message_ids
    else:
        unique_message_ids = 0
        max_repeat = 0
        mean_repeat = 0.0

    return SchemaReport(
        session_id=session_id,
        event_count=event_count,
        event_types=dict(event_types),
        assistant_block_types=dict(assistant_blocks),
        user_block_types=dict(user_blocks),
        unique_message_ids=unique_message_ids,
        max_message_id_repeat=max_repeat,
        mean_message_id_repeat=round(mean_repeat, 2),
        thinking_visible_count=thinking_visible,
        thinking_redacted_count=thinking_redacted,
        tools_defined=sorted(tools_defined),
        tools_called=sorted(tools_called),
        usage_totals=usage_totals,
        skipped_event_types=dict(skipped),
    )


def render_text(r: SchemaReport) -> str:
    lines = [
        f"== Session {r.session_id or '<none>'} ==",
        f"events: {r.event_count}",
        "event types:       " + "  ".join(f"{k}={v}" for k, v in sorted(r.event_types.items(), key=lambda x: -x[1])),
        "assistant blocks:  " + "  ".join(f"{k}={v}" for k, v in sorted(r.assistant_block_types.items(), key=lambda x: -x[1])),
        "user blocks:       " + "  ".join(f"{k}={v}" for k, v in sorted(r.user_block_types.items(), key=lambda x: -x[1])),
        f"message.id:        unique={r.unique_message_ids}  max_repeat={r.max_message_id_repeat}  mean_repeat={r.mean_message_id_repeat}",
        f"thinking blocks:   visible={r.thinking_visible_count}  redacted={r.thinking_redacted_count}",
        f"tools defined:     {r.tools_defined}",
        f"tools called:      {r.tools_called}",
        "usage totals:      " + "  ".join(f"{k}={v:,}" for k, v in r.usage_totals.items()),
    ]
    if r.skipped_event_types:
        skipped_summary = "  ".join(f"{k}({v})" for k, v in sorted(r.skipped_event_types.items(), key=lambda x: -x[1]))
        lines.append(f"skipped events:    {skipped_summary}")
    return "\n".join(lines)


def render_json(r: SchemaReport) -> str:
    return json.dumps(asdict(r), ensure_ascii=False, indent=2)
