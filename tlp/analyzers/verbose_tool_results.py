from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


def _ngrams(text: str, n: int) -> set[str]:
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


class VerboseToolResultsAnalyzer(BaseAnalyzer):
    name = "verbose_tool_results"
    lever = LeverCategory.VERBOSE_TOOL_RESULTS
    usage_bucket = "input"
    prescription = None
    measurement_basis = "heuristic"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("verbose_tool_results", {})
        ratio_thresh = float(c.get("citation_ratio_threshold", 0.10))
        window = int(c.get("followup_window_turns", 3))
        n = int(c.get("ngram", 3))

        findings: list[Finding] = []
        total = 0

        for ti, turn in enumerate(trace.turns):
            if turn.role != "tool_result":
                continue
            for bi, b in enumerate(turn.blocks):
                if b.kind != "tool_result" or not b.text or b.tokens < 20:
                    continue
                result_ngrams = _ngrams(b.text, n)
                if not result_ngrams:
                    continue
                cited: set[str] = set()
                for j in range(ti + 1, min(ti + 1 + window, len(trace.turns))):
                    if trace.turns[j].role != "assistant":
                        continue
                    for bb in trace.turns[j].blocks:
                        if bb.kind == "text" and bb.text:
                            cited |= _ngrams(bb.text, n)
                citation_ratio = len(result_ngrams & cited) / len(result_ngrams)
                if citation_ratio < ratio_thresh:
                    leak = int(b.tokens * (1 - citation_ratio))
                    total += leak
                    findings.append(Finding(
                        location=f"turn[{ti}].blocks[{bi}]",
                        leaked_tokens=leak,
                        confidence="low",
                        suggestion=(
                            f"tool result ({b.tokens} tok) cited only {citation_ratio:.0%} in next "
                            f"{window} turns — verify the output was actually unused for "
                            f"decision-making before truncating; low citation can mean "
                            f"'used for cognitive context but not echoed' rather than 'waste'"
                        ),
                        evidence={
                            "tool_use_id": b.tool_use_id,
                            "citation_ratio": round(citation_ratio, 3),
                            "result_tokens": b.tokens,
                        },
                        evidence_kind="signal",
                    ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
