# Token Leak Profiler v0.6.0 — Design Spec

- **Date**: 2026-05-29
- **Owner**: ljk9121
- **Status**: Approved (autonomous) → ready for implementation plan
- **Builds on**: [v0.5 design](2026-05-29-token-leak-profiler-v0.5-design.md)
- **Spec-checklist applied**: rules 1, 2, 5 self-applied
- **External source**: completes [blog 6-lever taxonomy](https://leejk.vercel.app/notes/2026-05-21-token-frugality) — 6/6

## 1. Goal

Add `mcp_server_overhead` analyzer (confirmed). Brings blog lever coverage from 5/6 (v0.5.0) → 6/6.

## 2. Inputs & Schema Discovery Evidence

### 2.1 Field-level discovery (rule 1 applied)

Inspected real session `af0b624f`. Findings:

**MCP activation events:**
- NOT a separate event type. Embedded in `user`/`assistant` events with `attachment.type == "deferred_tools_delta"`.
- Sample structure:
  ```json
  {
    "type": "user",
    "attachment": {
      "type": "deferred_tools_delta",
      "addedNames": ["mcp__pal__chat", "mcp__pal__consensus", ...
                     "mcp__playwright__browser_click", ...]
    }
  }
  ```
- Tool names follow `mcp__<server>__<tool_name>` convention. Server name extractable.

**Tool call distribution in this session (273 deduped assistant messages):**
- TaskUpdate: 160, TaskCreate: 85, Agent: 85, Bash: 75
- Edit: 23, AskUserQuestion: 20, Write: 15, Read: 15, Skill: 12
- ToolSearch: 4, WebFetch: 1
- **MCP tools called: 0** (despite ~50+ mcp__ tools activated)

**Net activation observation:**
- `mcp__pal__*` (12 tools activated, 0 called) — entire `pal` server unused
- `mcp__playwright__*` (~25 tools activated, 0 called) — entire `playwright` server unused
- `mcp__claude_ai_*` (6 tools activated, 0 called) — entire `claude_ai_*` triple unused

### 2.2 Rule 5 application

| Aspect | Status |
|---|---|
| Measurable? | ✅ `addedNames` ∖ `called_names` set difference, grouped by `mcp__<server>__` prefix |
| 1:1 prescription? | ✅ "disable `<server>` in settings (~/.claude/claude.json or settings.json)" — direct |
| Confirmed leak | ✅ |

## 3. Architecture

Unchanged. One new analyzer.

```
tlp/
  types.py                        # MODIFY: add MCP_SERVER_OVERHEAD enum value
  analyzers/
    __init__.py                   # MODIFY: register mcp_server_overhead
    mcp_server_overhead.py        # NEW
  parser/
    claude_code.py                # MODIFY: pass-through attachment.addedNames into trace metadata
  types.py                        # MODIFY: ParsedTrace.activated_tool_names: frozenset[str]
  config/
    defaults.yaml                 # MODIFY: mcp_server_overhead block
tests/
  fixtures/synthetic/
    mcp_unused_trace.jsonl        # NEW: activations + zero calls for one server
  test_analyzers/
    test_mcp_server_overhead.py   # NEW
  test_types.py                   # MODIFY: enum 10 → 11, ParsedTrace field
  test_parser.py                  # EXTEND: addedNames collection
  test_cli_e2e.py                 # MODIFY: 10 → 11
```

## 4. Data Model

### 4.1 `LeverCategory` adds one

```python
class LeverCategory(Enum):
    ...
    MCP_SERVER_OVERHEAD = "mcp_server_overhead"   # NEW
```

### 4.2 `ParsedTrace.activated_tool_names`

```python
@dataclass(frozen=True)
class ParsedTrace:
    ...
    label: str | None = None
    is_subagent: bool = False
    activated_tool_names: frozenset[str] = field(default_factory=frozenset)   # NEW
```

Parser collects all `addedNames` strings from `deferred_tools_delta` attachments across events, deduplicated.

## 5. Parser Changes

In the first-pass loop of `parse()`, after JSON decode:

```python
attachment = event.get("attachment")
if isinstance(attachment, dict) and attachment.get("type") == "deferred_tools_delta":
    added = attachment.get("addedNames")
    if isinstance(added, list):
        activated_names.update(str(n) for n in added)
```

Initialize `activated_names: set[str] = set()` before the loop. Pass into `ParsedTrace` as `activated_tool_names=frozenset(activated_names)`.

## 6. Analyzer Spec

### `mcp_server_overhead` (confirmed)

**Bucket:** `input` (tool definitions live in the cached system-prompt prefix).

**Algorithm:**
1. From `trace.activated_tool_names`, filter only `mcp__*` prefixed.
2. From `trace.turns`, collect actually-called tool names (union of `tool_use.name` across all assistant turns).
3. Group activated MCP tools by server (string between `mcp__` and the next `__`).
4. For each server: count activated tools and intersect with called tools. If `called_count == 0`, the entire server is "unused."
5. For unused servers, leaked_tokens = `sum(activated_tool_count_per_server) × estimated_tokens_per_tool_def` (config `estimated_tokens_per_tool_def`, default 200).
6. Emit a single Finding per unused server (multiple if many).

**Suggestion per Finding:**
> "MCP server '{server}' has {count} tools activated but 0 called this session. Estimated overhead: {leaked} tok in the cached system prompt. Disable in settings (~/.claude/claude.json or claude code settings) if not needed."

**Evidence:** `{server_name, activated_tool_count, called_count, estimated_tokens_per_tool_def}`.

**Evidence kind:** `confirmed`. **Confidence:** `high` if activated_count ≥ 10, `mid` else.

**Rule 5 justification:** User can directly disable the MCP server in settings — one-line config change per unused server.

### Edge cases

- No activation events in trace → empty report (most older Claude Code sessions won't have `deferred_tools_delta`).
- All activated MCP tools called at least once → empty report (efficient use).
- Some tools of a server called, others not → server **not** flagged (partial use OK; tool-level granularity is v0.7).
- Non-MCP tools (TaskUpdate, Bash etc.) ignored — only `mcp__*` prefix considered.

## 7. CLI Changes

None. New analyzer auto-registers.

## 8. Config

`tlp/config/defaults.yaml`:

```yaml
mcp_server_overhead:
  estimated_tokens_per_tool_def: 200
```

## 9. Reporter Changes

None. Standard analyzer; rich table + JSON renderer handle it transparently.

README: lever catalog 10 → 11.

## 10. Error Handling

- Missing/malformed `addedNames` list → skip silently (don't crash on optional schema variation).
- Empty `activated_tool_names` → empty report.

## 11. Testing Strategy

### v0.5 regression
134 tests must stay green. Test count assertions update from 10 → 11.

### New tests for `mcp_server_overhead`:
- positive: fixture with 5 activated `mcp__demo__*` tools + 0 calls → Finding with leaked_tokens > 0
- negative: 5 activated + 5 called → empty report
- partial: 5 activated, 2 called (3 unused) → still empty (server-level granularity)
- non-MCP tools ignored: 5 activated `mcp__demo__*` + 5 called `TaskUpdate` → flagged (MCP not called)

### Parser test:
- `addedNames` from `deferred_tools_delta` collected into `ParsedTrace.activated_tool_names`

## 12. Migration & Versioning

- `__version__ = "0.6.0"`
- `pyproject.toml` synced

## 13. v0.7+ Backlog

- Tool-level granularity (which specific tools within a server unused, vs whole-server)
- "Active but rarely used" — call count below threshold
- README lever doc auto-generated from analyzer metadata (single source of truth)
- Identity reframe (CLI rename)

## 14. Open Questions

- `estimated_tokens_per_tool_def: 200` is a heuristic. Real MCP tool definitions can range from ~100 to ~1000 tokens depending on schema verbosity. Calibrate against real `tools` payload measurement if accuracy matters; otherwise the 200 default is conservative.
