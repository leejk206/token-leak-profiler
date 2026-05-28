"""Importing this package auto-registers all built-in analyzers."""
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.analyzers import (  # noqa: F401  (imports trigger registration)
    stale_context,
    redundant_restatement,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
    cache_turnover_cost,
)

__all__ = ["BaseAnalyzer", "registry"]
