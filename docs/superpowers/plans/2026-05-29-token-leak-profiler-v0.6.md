# Token Leak Profiler v0.6.0 Implementation Plan

> Use subagent-driven-development. 3 tasks.

**Goal:** Add `mcp_server_overhead` confirmed analyzer + parser `activated_tool_names`.

**Spec:** [2026-05-29-token-leak-profiler-v0.6-design.md](../specs/2026-05-29-token-leak-profiler-v0.6-design.md)

---

## Task 1: types + parser

**Files:**
- Modify: `tlp/types.py` (enum + ParsedTrace.activated_tool_names)
- Modify: `tlp/parser/claude_code.py` (collect addedNames)
- Modify: `tests/test_types.py` (enum 10→11, default frozenset())
- Modify: `tests/test_parser.py` (addedNames collection)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_types.py`:

```python
def test_lever_category_v0_6_set():
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "cache_turnover_cost",
        "subagent_context_overdump", "system_prompt_audit",
        "roundtrip_inflation", "tool_result_repetition",
        "mcp_server_overhead",
    }


def test_parsed_trace_activated_tool_names_default_empty():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    assert t.activated_tool_names == frozenset()


def test_parsed_trace_activated_tool_names_explicit():
    from tlp.types import ParsedTrace, PricingTable
    t = ParsedTrace(
        session_id="x", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
        activated_tool_names=frozenset({"mcp__demo__a", "mcp__demo__b"}),
    )
    assert "mcp__demo__a" in t.activated_tool_names
```

Append to `tests/test_parser.py`:

```python
def test_parse_collects_deferred_tools_delta_addedNames():
    import tempfile, json as json_module
    events = [
        {"type": "user", "sessionId": "x", "uuid": "u1",
         "attachment": {"type": "deferred_tools_delta",
                        "addedNames": ["mcp__demo__a", "mcp__demo__b", "Bash"]},
         "message": {"role": "user", "content": "hi"}},
        {"type": "assistant", "sessionId": "x", "uuid": "a1",
         "message": {"role": "assistant", "id": "m1",
                     "content": [{"type": "text", "text": "ok"}],
                     "usage": {"input_tokens": 1, "output_tokens": 1,
                               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        t = parse(path)
        assert "mcp__demo__a" in t.activated_tool_names
        assert "Bash" in t.activated_tool_names
    finally:
        path.unlink()
```

- [ ] **Step 2: Run failing**

```bash
uv run pytest tests/test_types.py tests/test_parser.py -v
```

Expected: new tests FAIL.

- [ ] **Step 3: Modify `tlp/types.py`**

Add to `LeverCategory`:

```python
MCP_SERVER_OVERHEAD = "mcp_server_overhead"
```

Add to `ParsedTrace` (after `is_subagent`, last field):

```python
activated_tool_names: frozenset[str] = field(default_factory=frozenset)
```

Make sure `field` is imported from `dataclasses` (may already be).

- [ ] **Step 4: Modify `tlp/parser/claude_code.py`**

Initialize before the first-pass loop (alongside `ai_title`, `is_subagent`):

```python
    activated_names: set[str] = set()
```

In the loop body, after `event = json.loads(raw_line)` succeeds:

```python
        attachment = event.get("attachment")
        if isinstance(attachment, dict) and attachment.get("type") == "deferred_tools_delta":
            added = attachment.get("addedNames")
            if isinstance(added, list):
                activated_names.update(str(n) for n in added)
```

In the final `return ParsedTrace(...)`, add:

```python
        activated_tool_names=frozenset(activated_names),
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_types.py tests/test_parser.py -v
uv run pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add tlp/types.py tlp/parser/claude_code.py tests/test_types.py tests/test_parser.py
git commit -m "feat(types,parser): LeverCategory.MCP_SERVER_OVERHEAD + ParsedTrace.activated_tool_names"
```

---

## Task 2: mcp_server_overhead analyzer

**Files:**
- Create: `tlp/analyzers/mcp_server_overhead.py`
- Create: `tests/fixtures/synthetic/mcp_unused_trace.jsonl`
- Create: `tests/test_analyzers/test_mcp_server_overhead.py`
- Modify: `tlp/config/defaults.yaml`
- Modify: `tlp/analyzers/__init__.py`

- [ ] **Step 1: Add config**

Append to `tlp/config/defaults.yaml`:

```yaml
mcp_server_overhead:
  estimated_tokens_per_tool_def: 200
```

- [ ] **Step 2: Write fixture — 5 mcp__demo__* tools activated, 0 called**

Create `tests/fixtures/synthetic/mcp_unused_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"mcp-test","uuid":"u1","attachment":{"type":"deferred_tools_delta","addedNames":["mcp__demo__a","mcp__demo__b","mcp__demo__c","mcp__demo__d","mcp__demo__e"]},"message":{"role":"user","content":"start"}}
{"type":"assistant","sessionId":"mcp-test","uuid":"a1","message":{"role":"assistant","id":"m1","content":[{"type":"tool_use","id":"tu_1","name":"Bash","input":{"cmd":"ls"}}],"usage":{"input_tokens":10,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"mcp-test","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"ok"}]}}
{"type":"assistant","sessionId":"mcp-test","uuid":"a2","message":{"role":"assistant","id":"m2","content":[{"type":"text","text":"done"}],"usage":{"input_tokens":15,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_analyzers/test_mcp_server_overhead.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.mcp_server_overhead import MCPServerOverheadAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "mcp_unused_trace.jsonl"


def test_flags_unused_mcp_server():
    trace = parse(FIX)
    r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert len(r.findings) == 1
    f = r.findings[0]
    assert "demo" in f.location
    # 5 tools × 200 tok = 1000
    assert f.leaked_tokens == 1000
    assert f.evidence_kind == "confirmed"
    assert f.evidence["activated_tool_count"] == 5
    assert f.evidence["called_count"] == 0


def test_no_finding_when_called_at_least_once():
    """If at least one tool of the server is called, server isn't fully unused."""
    import tempfile, json as json_module
    events = [
        {"type":"user","sessionId":"x","uuid":"u1",
         "attachment":{"type":"deferred_tools_delta","addedNames":["mcp__demo__a","mcp__demo__b"]},
         "message":{"role":"user","content":"hi"}},
        {"type":"assistant","sessionId":"x","uuid":"a1",
         "message":{"role":"assistant","id":"m1",
                    "content":[{"type":"tool_use","id":"tu_1","name":"mcp__demo__a","input":{}}],
                    "usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        trace = parse(path)
        r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()


def test_no_finding_when_no_activations():
    """Trace with no deferred_tools_delta → empty."""
    minimal = Path(__file__).parent.parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"
    trace = parse(minimal)
    r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []


def test_non_mcp_tools_ignored():
    """Activated non-MCP tools (e.g. Bash, TaskUpdate) don't trigger this lever."""
    import tempfile, json as json_module
    events = [
        {"type":"user","sessionId":"x","uuid":"u1",
         "attachment":{"type":"deferred_tools_delta","addedNames":["Bash","TaskUpdate","Edit"]},
         "message":{"role":"user","content":"hi"}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in events:
            f.write(json_module.dumps(e) + "\n")
        path = Path(f.name)
    try:
        trace = parse(path)
        r = MCPServerOverheadAnalyzer().analyze(trace, load_defaults())
        assert r.findings == []
    finally:
        path.unlink()
```

- [ ] **Step 4: Run failing**

```bash
uv run pytest tests/test_analyzers/test_mcp_server_overhead.py -v
```

- [ ] **Step 5: Create `tlp/analyzers/mcp_server_overhead.py`**

```python
from __future__ import annotations
from collections import defaultdict
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class MCPServerOverheadAnalyzer(BaseAnalyzer):
    name = "mcp_server_overhead"
    lever = LeverCategory.MCP_SERVER_OVERHEAD
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("mcp_server_overhead", {})
        est_per_tool = int(c.get("estimated_tokens_per_tool_def", 200))

        # Group activated MCP tools by server
        # mcp__<server>__<tool> → server name extraction
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

        # Collect called tool names from assistant tool_use blocks
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
            leaked = activated_count * est_per_tool
            total += leaked
            confidence = "high" if activated_count >= 10 else "mid"
            findings.append(Finding(
                location=f"mcp_server[{server}]",
                leaked_tokens=leaked,
                confidence=confidence,
                suggestion=(
                    f"MCP server '{server}' has {activated_count} tools activated "
                    f"but 0 called this session. Estimated overhead: {leaked} tok "
                    f"in the cached system prompt. Disable in settings "
                    f"(~/.claude/claude.json or claude code settings) if not needed."
                ),
                evidence={
                    "server_name": server,
                    "activated_tool_count": activated_count,
                    "called_count": 0,
                    "estimated_tokens_per_tool_def": est_per_tool,
                },
                evidence_kind="confirmed",
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 6: Register**

Add `mcp_server_overhead` to `tlp/analyzers/__init__.py` imports.

- [ ] **Step 7: Run tests + update e2e count**

```bash
uv run pytest tests/test_analyzers/test_mcp_server_overhead.py -v
uv run pytest -q
```

If `test_cli_e2e.py` fails on analyzer count or name set, update: 10 → 11, add "mcp_server_overhead".

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/mcp_server_overhead.py tlp/analyzers/__init__.py tlp/config/defaults.yaml tests/fixtures/synthetic/mcp_unused_trace.jsonl tests/test_analyzers/test_mcp_server_overhead.py tests/test_cli_e2e.py
git commit -m "feat(analyzers): mcp_server_overhead (confirmed) — unused MCP server detection"
```

---

## Task 3: version bump + README + Tagline

**Files:**
- Modify: `tlp/__init__.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Version bump**

`tlp/__init__.py`: `__version__ = "0.6.0"`
`pyproject.toml`: `version = "0.6.0"`

- [ ] **Step 2: README update**

Update the lever catalog to 11 entries (5 confirmed + 6 signal). Add `mcp_server_overhead` to confirmed table:

```markdown
| mcp_server_overhead | input | activated MCP server with 0 calls this session | disable in settings (~/.claude/claude.json) |
```

Update the "v0.5.0 aligned to blog 6 levers: 5/6" sentence to "v0.6.0 aligned to blog 6 levers: **6/6** (full coverage)".

- [ ] **Step 3: Run full suite + ruff**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: ~140 pass, ruff clean.

- [ ] **Step 4: Verify version**

```bash
uv run python -c "import tlp; print(tlp.__version__)"
grep '^version' pyproject.toml
```

Both `0.6.0`.

- [ ] **Step 5: Commit**

```bash
git add tlp/__init__.py pyproject.toml README.md
git commit -m "docs(v0.6.0): bump 0.6.0 + README mcp_server_overhead in catalog (blog 6/6)"
```

---

## Execution: subagent-driven, user review skipped per session instruction.
