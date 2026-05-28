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
        msg = event.get("message")
        if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
            warning_msg = f"line {line_no}: skipping type={ev_type!r}"
            warnings.append(warning_msg)
            logging.warning(warning_msg)
            continue

        # Tool definitions can appear nested in assistant messages (system_tools)
        # or as top-level field on event. Capture from both; dedup by name below.
        for td in (event.get("tools") or []) + (msg.get("tools") or []):
            name = td.get("name")
            if name and name not in tool_defs:
                tool_defs[name] = ToolDef(
                    name=name,
                    schema_json=td,
                    tokens=count_tokens_of(td),
                )

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
        else:  # assistant
            blocks = _parse_assistant_content(msg.get("content", []))
            usage = _parse_usage(msg.get("usage"))
            turns.append(Turn(
                index=next_index, role="assistant",
                blocks=tuple(blocks), usage=usage,
            ))
            next_index += 1

    return ParsedTrace(
        session_id=session_id,
        turns=tuple(turns),
        tool_defs=dict(tool_defs),
        pricing=pricing,
    )


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
