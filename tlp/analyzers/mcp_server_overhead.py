from __future__ import annotations
from collections import defaultdict
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class MCPServerOverheadAnalyzer(BaseAnalyzer):
    name = "mcp_server_overhead"
    lever = LeverCategory.MCP_SERVER_OVERHEAD
    usage_bucket = "input"
    prescription = "Disable unused MCP server in Claude Code settings (~/.claude/claude.json)"
    measurement_basis = "estimated"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("mcp_server_overhead", {})
        est_per_tool = int(c.get("estimated_tokens_per_tool_def", 200))
        measurements: dict[str, int] = config.get("__measurements", {})

        server_to_activated: defaultdict[str, set[str]] = defaultdict(set)
        for tool_name in trace.activated_tool_names:
            if not tool_name.startswith("mcp__"):
                continue
            rest = tool_name[len("mcp__"):]
            sep = rest.find("__")
            if sep < 0:
                continue
            server = rest[:sep]
            server_to_activated[server].add(tool_name)

        if not server_to_activated:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        called_names: set[str] = set()
        for turn in trace.turns:
            if turn.role != "assistant":
                continue
            for b in turn.blocks:
                if b.kind == "tool_use" and b.tool_name:
                    called_names.add(b.tool_name)

        findings = []
        total = 0
        for server, activated_set in sorted(server_to_activated.items()):
            called_count = len(activated_set & called_names)
            if called_count > 0:
                continue
            activated_count = len(activated_set)
            # Determine measurement coverage for this server's tools
            covered = [t for t in activated_set if t in measurements]
            coverage = len(covered) / activated_count if activated_count else 0.0
            if coverage == 1.0:
                leaked = sum(measurements[t] for t in activated_set)
                basis = "measured"
                evidence_kind = "confirmed"
            elif coverage > 0:
                leaked = (sum(measurements[t] for t in covered)
                          + (activated_count - len(covered)) * est_per_tool)
                basis = "mixed"
                evidence_kind = "estimated"
            else:
                leaked = activated_count * est_per_tool
                basis = "heuristic"
                evidence_kind = "estimated"
            total += leaked
            confidence = "high" if activated_count >= 10 else "mid"
            findings.append(Finding(
                location=f"mcp_server[{server}]",
                leaked_tokens=leaked,
                confidence=confidence,
                suggestion=(
                    f"MCP server '{server}' has {activated_count} tools activated "
                    f"but 0 called this session. "
                    f"Estimated overhead: {leaked} tok. "
                    f"Disable in settings (~/.claude/claude.json) if not needed."
                ),
                evidence={
                    "server_name": server,
                    "activated_tool_count": activated_count,
                    "called_count": 0,
                    "measurement_basis": basis,
                    "measurement_coverage_ratio": round(coverage, 3),
                },
                evidence_kind=evidence_kind,
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
