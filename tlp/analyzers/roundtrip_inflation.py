from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class RoundtripInflationAnalyzer(BaseAnalyzer):
    name = "roundtrip_inflation"
    lever = LeverCategory.ROUNDTRIP_INFLATION
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("roundtrip_inflation", {})
        short_threshold = int(c.get("short_user_msg_chars", 20))
        min_run = int(c.get("min_short_run", 3))
        est_resp = int(c.get("estimated_assistant_response_tokens", 500))

        runs = []
        run_start = None
        run_length = 0

        for ti, turn in enumerate(trace.turns):
            if turn.role != "user":
                continue
            text_total = sum(
                len(b.text or "")
                for b in turn.blocks
                if b.kind == "text"
            )
            if text_total < short_threshold and text_total > 0:
                if run_start is None:
                    run_start = ti
                run_length += 1
            else:
                if run_length >= min_run:
                    runs.append((run_start, ti - 1, run_length))
                run_start = None
                run_length = 0

        if run_length >= min_run:
            runs.append((run_start, len(trace.turns) - 1, run_length))

        if not runs:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        findings = []
        total = 0
        for start, end, length in runs:
            leaked = (length - 1) * est_resp
            total += leaked
            findings.append(Finding(
                location=f"turn[{start}..{end}]",
                leaked_tokens=leaked,
                confidence="low",
                suggestion=(
                    f"{length} consecutive short user messages (< {short_threshold} chars). "
                    f"Could have been bundled into one Plan-mode session or "
                    f"single AskUserQuestion."
                ),
                evidence={
                    "run_length": length,
                    "start_turn": start,
                    "end_turn": end,
                    "short_threshold": short_threshold,
                },
                evidence_kind="signal",
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
