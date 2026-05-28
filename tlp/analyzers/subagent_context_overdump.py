from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class SubagentContextOverdumpAnalyzer(BaseAnalyzer):
    name = "subagent_context_overdump"
    lever = LeverCategory.SUBAGENT_CONTEXT_OVERDUMP
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        if not trace.is_subagent:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        c = config.get("subagent_context_overdump", {})
        min_tokens = int(c.get("min_subagent_prompt_tokens", 5000))
        baseline = int(c.get("baseline_subagent_prompt_tokens", 1000))

        first_user_turn = next(
            (t for t in trace.turns if t.role == "user"), None
        )
        if first_user_turn is None:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        first_prompt_tokens = sum(
            b.tokens for b in first_user_turn.blocks if b.kind == "text"
        )
        if first_prompt_tokens < min_tokens:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        leaked = first_prompt_tokens - baseline
        confidence = "high" if first_prompt_tokens > 20000 else "mid"
        finding = Finding(
            location="subagent_prompt",
            leaked_tokens=leaked,
            confidence=confidence,
            suggestion=(
                f"Subagent dispatch prompt is {first_prompt_tokens} tok "
                f"(recommended baseline: {baseline} tok). Narrow the scope on "
                f"next dispatch — pass only specific context needed for the task."
            ),
            evidence={
                "first_prompt_tokens": first_prompt_tokens,
                "baseline": baseline,
            },
            evidence_kind="confirmed",
        )
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=leaked, leaked_cost_usd=0.0, findings=[finding],
        )
