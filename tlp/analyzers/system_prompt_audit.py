from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.analyzers._helpers import estimate_stable_prefix
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class SystemPromptAuditAnalyzer(BaseAnalyzer):
    name = "system_prompt_audit"
    lever = LeverCategory.SYSTEM_PROMPT_AUDIT
    usage_bucket = "input"
    prescription = None
    measurement_basis = "measured"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        if trace.is_subagent:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        c = config.get("system_prompt_audit", {})
        min_tokens = int(c.get("min_system_prompt_tokens", 15000))
        baseline = int(c.get("baseline_system_prompt_tokens", 10000))

        # Collect (cache_read, cache_creation) per assistant turn
        usages = []
        for turn in trace.turns:
            if turn.role != "assistant" or turn.usage is None:
                continue
            usages.append((turn.usage.cache_read_tokens, turn.usage.cache_creation_tokens))

        if len(usages) < 2:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        # Identify invalidation events: actual_cr < (prev_cr + prev_cc) by >= 5000
        invalidation_cr_values = []
        for i in range(1, len(usages)):
            prev_cr, prev_cc = usages[i - 1]
            actual_cr = usages[i][0]
            expected = prev_cr + prev_cc
            if expected - actual_cr >= 5000:
                invalidation_cr_values.append(actual_cr)

        stable_prefix = estimate_stable_prefix(invalidation_cr_values)
        if stable_prefix is None or stable_prefix < min_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        leaked = stable_prefix - baseline
        finding = Finding(
            location="system_prompt",
            leaked_tokens=leaked,
            confidence="low",
            suggestion=(
                f"Stable system-prompt prefix estimated at {stable_prefix} tok "
                f"(baseline: ~{baseline} tok). Skills, plugins, or MCP servers "
                f"loaded but unused contribute. Inspect /config to disable unused skills."
            ),
            evidence={
                "stable_prefix_tokens": stable_prefix,
                "baseline": baseline,
            },
            evidence_kind="signal",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=leaked, leaked_cost_usd=0.0, findings=[finding],
        )
