from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, ClassVar


class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    TOOL_SCHEMA_BLOAT = "tool_schema_bloat"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"


BlockKind = Literal["text", "tool_use", "tool_result", "thinking"]
TurnRole = Literal["user", "assistant", "tool_result"]
UsageBucket = Literal["input", "output", "cache_read", "cache_creation"]
Confidence = Literal["low", "mid", "high"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str | None
    tool_name: str | None
    tool_input: dict | None
    tool_use_id: str | None
    tokens: int


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


@dataclass(frozen=True)
class Turn:
    index: int
    role: TurnRole
    blocks: tuple[Block, ...]
    usage: Usage | None


@dataclass(frozen=True)
class ToolDef:
    name: str
    schema_json: dict
    tokens: int


@dataclass(frozen=True)
class PricingTable:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_creation_per_mtok: float

    def cost(self, tokens: int, bucket: UsageBucket) -> float:
        rates = {
            "input": self.input_per_mtok,
            "output": self.output_per_mtok,
            "cache_read": self.cache_read_per_mtok,
            "cache_creation": self.cache_creation_per_mtok,
        }
        return tokens / 1_000_000 * rates[bucket]


@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable


@dataclass
class Finding:
    location: str
    leaked_tokens: int
    confidence: Confidence
    suggestion: str
    evidence: dict = field(default_factory=dict)


@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int
    leaked_cost_usd: float
    findings: list[Finding]
    error: str | None = None
