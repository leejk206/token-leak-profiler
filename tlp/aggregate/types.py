from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    label: str
    path: Path
    turn_count: int
    total_cost_usd: float
    effective_leak_cost_usd: float
    leak_ratio: float
    dominant_lever: str | None
    is_outlier: bool


@dataclass(frozen=True)
class AggregateReport:
    sessions: tuple[SessionRow, ...]
    total_cost_usd: float
    total_effective_leak_usd: float
    median_leak_ratio: float
    outlier_threshold: float
    session_count: int
