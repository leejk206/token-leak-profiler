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
        min_use_ratio = float(c.get("min_use_ratio", 0.3))
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

        def _compute_basis(tool_set: set[str]) -> tuple[int, str, str]:
            """Returns (leaked_tokens, basis, evidence_kind) for a set of unused tools."""
            if not tool_set:
                return 0, "heuristic", "estimated"
            covered = [t for t in tool_set if t in measurements]
            coverage = len(covered) / len(tool_set)
            if coverage == 1.0:
                leaked = sum(measurements[t] for t in tool_set)
                return leaked, "measured", "confirmed"
            elif coverage > 0:
                leaked = (sum(measurements[t] for t in covered)
                          + (len(tool_set) - len(covered)) * est_per_tool)
                return leaked, "mixed", "estimated"
            else:
                return len(tool_set) * est_per_tool, "heuristic", "estimated"

        findings = []
        total = 0
        for server, activated_set in sorted(server_to_activated.items()):
            used_set = activated_set & called_names
            used_count = len(used_set)
            total_count = len(activated_set)

            if used_count == 0:
                # Server-level unused (existing v0.6 path)
                leaked, basis, evidence_kind = _compute_basis(activated_set)
                covered = [t for t in activated_set if t in measurements]
                coverage = len(covered) / total_count if total_count else 0.0
                confidence = "high" if total_count >= 10 else "mid"
                findings.append(Finding(
                    location=f"mcp_server[{server}]",
                    leaked_tokens=leaked,
                    confidence=confidence,
                    suggestion=(
                        f"MCP server '{server}' has {total_count} tools activated "
                        f"but 0 called this session. "
                        f"Estimated overhead: {leaked} tok. "
                        f"Disable in settings (~/.claude/claude.json) if not needed."
                    ),
                    evidence={
                        "server_name": server,
                        "activated_tool_count": total_count,
                        "called_count": 0,
                        "measurement_basis": basis,
                        "measurement_coverage_ratio": round(coverage, 3),
                    },
                    evidence_kind=evidence_kind,
                ))
                total += leaked

            elif used_count / total_count < min_use_ratio:
                # Partial-use sub-case: flag the unused subset
                unused_subset = activated_set - called_names
                unused_count = len(unused_subset)
                leaked, basis, evidence_kind = _compute_basis(unused_subset)
                covered = [t for t in unused_subset if t in measurements]
                coverage = len(covered) / unused_count if unused_count else 0.0
                confidence = "high" if unused_count >= 10 else "mid"
                findings.append(Finding(
                    location=f"mcp_server[{server}].partial({unused_count}/{total_count})",
                    leaked_tokens=leaked,
                    confidence=confidence,
                    suggestion=(
                        f"MCP server '{server}' has {used_count}/{total_count} tools used "
                        f"this session; {unused_count} unused. Estimated overhead from unused "
                        f"subset: {leaked} tok. Inspect whether the unused tools warrant "
                        f"disabling the server or pruning at the tool level."
                    ),
                    evidence={
                        "server_name": server,
                        "total_tool_count": total_count,
                        "used_count": used_count,
                        "unused_count": unused_count,
                        "measurement_basis": basis,
                        "measurement_coverage_ratio": round(coverage, 3),
                    },
                    evidence_kind=evidence_kind,
                ))
                total += leaked
            # else: used_count / total_count >= min_use_ratio → server actively used, no finding

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
