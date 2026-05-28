"""Claude Code transcript JSONL parser.

Format (informally observed): each line is one event with top-level fields
`type`, `sessionId`, `uuid`, `timestamp`, `message`. The nested `message`
mirrors the Anthropic Messages API shape: string content for user text,
list-of-blocks for richer payloads. tool_result blocks appear in user-role
messages; we split those into their own ParsedTrace turns (role="tool_result")
so analyzers can target tool I/O directly.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Iterator

from tlp.types import (
    ParsedTrace, Turn, Block, Usage, ToolDef, PricingTable,
)
from tlp.tokenizer import count_tokens, count_tokens_of
from tlp.config import load_pricing


def parse(path: Path, *, pricing: PricingTable | None = None, strict: bool = False) -> ParsedTrace:
    pricing = pricing or load_pricing()
    session_id = ""
    turns: list[Turn] = []
    tool_defs: dict[str, ToolDef] = {}
    warnings: list[str] = []
    next_index = 0
    ai_title: str | None = None

    # First pass: parse + filter events. Claude Code streams a single assistant
    # response across multiple JSONL lines (one per content block) but each event
    # repeats the same `usage`. Grouping by `message.id` is required to avoid
    # token double-counting and to keep thinking blocks bundled with the
    # text/tool_use blocks that share their message.
    events: list[tuple[int, str, dict]] = []  # (line_no, ev_type, event)
    for raw_line, line_no in _iter_lines(path):
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as e:
            msg = f"line {line_no}: bad JSON: {e}"
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
            logging.warning(msg)
            continue

        if not session_id:
            session_id = event.get("sessionId", "") or session_id

        ev_type = event.get("type")
        # tools_changed events are real assistant messages with usage; normalize
        # so they flow through the same pipeline. Global message.id dedup
        # (later in second pass) prevents double-counting if any tools_changed
        # shares an id with a prior assistant event.
        if ev_type == "tools_changed":
            ev_type = "assistant"
        msg = event.get("message")

        # ai-title: extract first non-empty title text, then continue (skip)
        if ev_type == "ai-title" and ai_title is None:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    ai_title = content.strip()
            continue

        if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
            warning_msg = f"line {line_no}: skipping type={ev_type!r}"
            if strict:
                raise ValueError(warning_msg)
            warnings.append(warning_msg)
            logging.warning(warning_msg)
            continue

        # Tool defs may appear on any event; dedup by name.
        for td in (event.get("tools") or []) + (msg.get("tools") or []):
            name = td.get("name")
            if name and name not in tool_defs:
                tool_defs[name] = ToolDef(
                    name=name,
                    schema_json=td,
                    tokens=count_tokens_of(td),
                )

        events.append((line_no, ev_type, event))

    # Second pass: build turns, grouping consecutive assistant events with the
    # same `message.id` into a single Turn.
    seen_message_ids: set[str] = set()
    i = 0
    while i < len(events):
        _, ev_type, event = events[i]
        msg = event["message"]

        if ev_type == "user":
            user_blocks, tool_result_blocks = _split_user_blocks(msg.get("content", ""))
            if user_blocks:
                turns.append(Turn(
                    index=next_index, role="user",
                    blocks=tuple(user_blocks), usage=None,
                ))
                next_index += 1
            if tool_result_blocks:
                turns.append(Turn(
                    index=next_index, role="tool_result",
                    blocks=tuple(tool_result_blocks), usage=None,
                ))
                next_index += 1
            i += 1
        else:  # assistant — peek-ahead for same message.id grouping
            message_id = msg.get("id")
            grouped_content = list(msg.get("content", []) or [])
            grouped_usage = msg.get("usage")
            j = i + 1
            while j < len(events) and message_id:
                _, nxt_type, nxt_event = events[j]
                if nxt_type != "assistant":
                    break
                nxt_msg = nxt_event["message"]
                if nxt_msg.get("id") != message_id:
                    break
                grouped_content.extend(nxt_msg.get("content", []) or [])
                # All split events report the same usage; keep the one with
                # max output_tokens defensively in case logs ever diverge.
                nxt_usage = nxt_msg.get("usage")
                if _usage_output(nxt_usage) > _usage_output(grouped_usage):
                    grouped_usage = nxt_usage
                j += 1
            blocks = _parse_assistant_content(grouped_content)
            # Non-consecutive dedup: if this message.id was already seen in a
            # previous (non-consecutive) turn, null out usage so it isn't
            # counted again toward session totals.
            if message_id and message_id in seen_message_ids:
                grouped_usage = None
            elif message_id:
                seen_message_ids.add(message_id)
            usage = _parse_usage(grouped_usage)
            turns.append(Turn(
                index=next_index, role="assistant",
                blocks=tuple(blocks), usage=usage,
            ))
            next_index += 1
            i = j

    return ParsedTrace(
        session_id=session_id,
        turns=tuple(turns),
        tool_defs=dict(tool_defs),
        pricing=pricing,
        label=ai_title,
    )


def _usage_output(u) -> int:
    return int(u.get("output_tokens", 0) or 0) if isinstance(u, dict) else 0


def _iter_lines(path: Path) -> Iterator[tuple[str, int]]:
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                yield line, i


def _split_user_blocks(content) -> tuple[list[Block], list[Block]]:
    """Returns (user_text_blocks, tool_result_blocks)."""
    if isinstance(content, str):
        return [_text_block(content)], []
    user_blocks: list[Block] = []
    tool_results: list[Block] = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_result":
            inner = c.get("content")
            text = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
            tool_results.append(Block(
                kind="tool_result", text=text, tool_name=None,
                tool_input=None, tool_use_id=c.get("tool_use_id"),
                tokens=count_tokens(text),
            ))
        elif c.get("type") == "text":
            user_blocks.append(_text_block(c.get("text", "")))
    return user_blocks, tool_results


def _parse_assistant_content(content) -> list[Block]:
    blocks: list[Block] = []
    if isinstance(content, str):
        return [_text_block(content)]
    for c in content or []:
        if not isinstance(c, dict):
            continue
        ctype = c.get("type")
        if ctype == "text":
            blocks.append(_text_block(c.get("text", "")))
        elif ctype == "thinking":
            text = c.get("thinking", "") or c.get("text", "")
            blocks.append(Block(
                kind="thinking", text=text, tool_name=None,
                tool_input=None, tool_use_id=None,
                tokens=count_tokens(text),
            ))
        elif ctype == "tool_use":
            blocks.append(Block(
                kind="tool_use", text=None,
                tool_name=c.get("name"),
                tool_input=c.get("input") or {},
                tool_use_id=c.get("id"),
                tokens=count_tokens_of(c.get("input") or {}),
            ))
    return blocks


def _parse_usage(u) -> Usage | None:
    if not isinstance(u, dict):
        return None
    return Usage(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
    )


def _text_block(text: str) -> Block:
    return Block(
        kind="text", text=text, tool_name=None,
        tool_input=None, tool_use_id=None,
        tokens=count_tokens(text),
    )
