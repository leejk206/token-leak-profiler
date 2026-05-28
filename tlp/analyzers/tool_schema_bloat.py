from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class ToolSchemaBloatAnalyzer(BaseAnalyzer):
    name = "tool_schema_bloat"
    lever = LeverCategory.TOOL_SCHEMA_BLOAT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        called: set[str] = set()
        assistant_turns = 0
        for turn in trace.turns:
            if turn.role == "assistant":
                assistant_turns += 1
                for b in turn.blocks:
                    if b.kind == "tool_use" and b.tool_name:
                        called.add(b.tool_name)

        findings: list[Finding] = []
        total = 0
        if assistant_turns == 0:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        for name, td in trace.tool_defs.items():
            if name in called:
                continue
            leak = td.tokens * assistant_turns
            total += leak
            findings.append(Finding(
                location=f"tool_def[{name}]",
                leaked_tokens=leak,
                confidence="high",
                suggestion=(
                    f"tool '{name}' never called across {assistant_turns} assistant turns "
                    f"— remove from tools list to save ~{td.tokens} tok per turn"
                ),
                evidence={"tool_name": name, "per_turn_tokens": td.tokens,
                          "assistant_turns": assistant_turns},
            ))

        # Sort findings by leaked_tokens desc
        findings.sort(key=lambda f: f.leaked_tokens, reverse=True)
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
