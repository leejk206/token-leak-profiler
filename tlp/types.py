from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"
    CACHE_TURNOVER_COST = "cache_turnover_cost"
    SUBAGENT_CONTEXT_OVERDUMP = "subagent_context_overdump"
    SYSTEM_PROMPT_AUDIT = "system_prompt_audit"
    ROUNDTRIP_INFLATION = "roundtrip_inflation"
    TOOL_RESULT_REPETITION = "tool_result_repetition"
    MCP_SERVER_OVERHEAD = "mcp_server_overhead"


BlockKind = Literal["text", "tool_use", "tool_result", "thinking"]
TurnRole = Literal["user", "assistant", "tool_result"]
UsageBucket = Literal["input", "output", "cache_read", "cache_creation"]
Confidence = Literal["low", "mid", "high"]
EvidenceKind = Literal["confirmed", "signal"]


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
    timestamp: str | None = None


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
    label: str | None = None
    is_subagent: bool = False
    activated_tool_names: frozenset[str] = field(default_factory=frozenset)


@dataclass
class Finding:
    location: str
    leaked_tokens: int
    confidence: Confidence
    suggestion: str
    evidence: dict = field(default_factory=dict)
    evidence_kind: EvidenceKind = "confirmed"


@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int
    leaked_cost_usd: float
    findings: list[Finding]
    error: str | None = None

    @property
    def confirmed_tokens(self) -> int:
        return sum(f.leaked_tokens for f in self.findings if f.evidence_kind == "confirmed")

    @property
    def signal_tokens(self) -> int:
        return sum(f.leaked_tokens for f in self.findings if f.evidence_kind == "signal")
