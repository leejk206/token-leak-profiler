from __future__ import annotations
import json
from collections import defaultdict
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class ToolResultRepetitionAnalyzer(BaseAnalyzer):
    name = "tool_result_repetition"
    lever = LeverCategory.TOOL_RESULT_REPETITION
    usage_bucket = "input"
    prescription = None
    measurement_basis = "heuristic"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("tool_result_repetition", {})
        min_repeat = int(c.get("min_repeat", 2))

        # Map tool_use_id → result tokens
        tool_use_id_to_result_tokens = {}
        for turn in trace.turns:
            if turn.role != "tool_result":
                continue
            for b in turn.blocks:
                if b.kind == "tool_result" and b.tool_use_id:
                    tool_use_id_to_result_tokens[b.tool_use_id] = b.tokens

        # Group tool_use by (name, canonical_input)
        groups = defaultdict(list)
        for turn in trace.turns:
            if turn.role != "assistant":
                continue
            for b in turn.blocks:
                if b.kind != "tool_use" or not b.tool_name:
                    continue
                canonical = json.dumps(b.tool_input or {}, sort_keys=True, ensure_ascii=False)
                groups[(b.tool_name, canonical)].append(b.tool_use_id)

        findings = []
        total = 0
        for (tool_name, canonical), tool_use_ids in groups.items():
            if len(tool_use_ids) < min_repeat:
                continue
            result_tokens_list = [
                tool_use_id_to_result_tokens.get(tu_id, 0) for tu_id in tool_use_ids
            ]
            if not any(result_tokens_list):
                continue
            per_call = sum(result_tokens_list) // len(result_tokens_list)
            leaked = (len(tool_use_ids) - 1) * per_call
            if leaked <= 0:
                continue
            total += leaked
            findings.append(Finding(
                location=f"tool[{tool_name}].repeat({len(tool_use_ids)})",
                leaked_tokens=leaked,
                confidence="low",
                suggestion=(
                    f"Tool '{tool_name}' called {len(tool_use_ids)} times with identical "
                    f"input. Re-using the prior result instead of re-calling could save "
                    f"{leaked} tok."
                ),
                evidence={
                    "tool_name": tool_name,
                    "repeat_count": len(tool_use_ids),
                    "per_call_result_tokens": per_call,
                },
                evidence_kind="signal",
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
