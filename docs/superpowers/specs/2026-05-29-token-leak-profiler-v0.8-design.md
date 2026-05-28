# Token Leak Profiler v0.8.0 — Design Spec

- **Date**: 2026-05-29
- **Owner**: ljk9121
- **Status**: Approved (autonomous) → ready for plan
- **Builds on**: [v0.7 design](2026-05-29-token-leak-profiler-v0.7-design.md)

## 1. Goal

Two tracks:
- **Pre-commit hook**: Move rule self-application from CI-only to local commit gate.
- **`tlp count-tokens`**: New CLI subcommand to populate `measurements.yaml` from a user-supplied tools JSON file via Anthropic's `count_tokens` API. Closes v0.7 §14 open question (heuristic calibration).

## 2. Pre-commit hook

### 2.1 Config

New file `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: rules-self-application
        name: rules-self-application (rule 5/6 enforcement)
        entry: uv run pytest tests/test_rules_self_application.py -q
        language: system
        pass_filenames: false
        files: ^(tlp/analyzers/|tests/test_rules_self_application\.py)
        stages: [pre-commit]
      - id: ruff
        name: ruff
        entry: uv run ruff check .
        language: system
        pass_filenames: false
        stages: [pre-commit]
```

- Two hooks: rule self-application test (only fires when analyzer code changes) + ruff (always).
- `language: system` — uses host uv, no pre-commit-managed venv. Simpler, faster.
- `pass_filenames: false` — pytest takes its own args; we don't want pre-commit to append changed-file paths.

### 2.2 Install path

README adds:

```bash
uv run pre-commit install
```

Add `pre-commit>=3.7` to dev `[dependency-groups]`. Don't add to runtime deps (only contributors need it).

### 2.3 Why local-first, not CI-only

GitHub Actions isn't wired yet (no `.github/workflows/`). Pre-commit catches the same rule violations locally — *before* push. Adding CI later is orthogonal (and cheap once hook exists).

## 3. `tlp count-tokens` subcommand

### 3.1 Surface

```bash
tlp count-tokens --tools tools.json [--output measurements.yaml] [--model claude-opus-4-7] [--merge]
```

- `--tools`: path to JSON file containing Anthropic-format tool definitions (list of `{name, description, input_schema}`). Required.
- `--output`: target measurements yaml. Default `tlp/config/measurements.yaml`.
- `--model`: Anthropic model id for token counting. Default `claude-opus-4-7`. Different models can yield different counts; we use the project default.
- `--merge`: if set, merge into existing `measurements.yaml` (don't overwrite already-measured tools); otherwise overwrite the `tools:` mapping wholesale.

Requires `ANTHROPIC_API_KEY` env var. Fail fast with clear error if missing.

### 3.2 Algorithm

Per-tool token cost is the *marginal* cost of adding that tool to a baseline request. We need a baseline + per-tool measurement to isolate the contribution.

```python
def measure_tool(client, model: str, tool: dict, baseline_tokens: int) -> int:
    """Returns marginal tokens added by this single tool."""
    resp = client.messages.count_tokens(
        model=model,
        system="",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
    )
    return resp.input_tokens - baseline_tokens
```

Where `baseline_tokens` is the count for an empty `tools=[]` request with the same system + messages. Marginal cost = `with_tool - baseline`.

Pseudocode:
```python
client = anthropic.Anthropic()
baseline = client.messages.count_tokens(
    model=model,
    system="",
    messages=[{"role": "user", "content": "x"}],
    tools=[],
).input_tokens

result: dict[str, int] = {}
for tool in tools:
    name = tool["name"]
    marginal = measure_tool(client, model, tool, baseline)
    result[name] = marginal
```

### 3.3 tools.json format

Anthropic API format, list at top level:

```json
[
  {
    "name": "mcp__pal__chat",
    "description": "Chat with a model",
    "input_schema": {
      "type": "object",
      "properties": {"prompt": {"type": "string"}},
      "required": ["prompt"]
    }
  }
]
```

We don't generate this; users source it from MCP server introspection, Claude Code tool exports, or hand-write for one-off measurement. Out of scope for v0.8.

### 3.4 Output format

Same as existing `measurements.yaml`:

```yaml
tools:
  mcp__pal__chat: 412
  mcp__playwright__browser_click: 187
```

With `--merge`: preserve any keys already in target file unless explicitly re-measured. Without `--merge`: replace `tools:` mapping entirely.

### 3.5 Errors

- Missing `ANTHROPIC_API_KEY` → exit 1, message `"ANTHROPIC_API_KEY not set; required for tlp count-tokens"`.
- `--tools` path missing → exit 1.
- tools.json malformed (not list, missing required fields) → exit 1 with parse error.
- Anthropic API error (rate limit, auth) → bubble up SDK exception with brief context.
- Marginal < 1 (shouldn't happen for valid tools) → still write, log warning.

### 3.6 Rate / cost

`count_tokens` API: no message generation, low cost (~free at small scale per Anthropic). For 100 tools × 1 baseline + 100 measurements = 101 calls. Acceptable for one-off populate.

## 4. Files

```
tlp/
  cli.py                          # MODIFY: register count_tokens subcommand
  measurements/                   # NEW package
    __init__.py
    count_tokens.py               # NEW: anthropic SDK wrapper
.pre-commit-config.yaml           # NEW
README.md                         # MODIFY: install + count-tokens usage
pyproject.toml                    # MODIFY: __version__ 0.8.0, dev pre-commit dep
tests/
  test_count_tokens.py            # NEW: mock anthropic SDK, verify behavior
  fixtures/synthetic/
    tools_sample.json             # NEW: 2-3 mock tool defs for tests
```

## 5. Testing strategy

### 5.1 count-tokens tests

Mock `anthropic.Anthropic` client. Tests verify:
- Baseline + per-tool marginal calculation correct
- Output yaml structure matches `measurements.yaml` schema
- `--merge` preserves existing keys not in input
- Missing API key → exit 1 + message
- Malformed tools.json → exit 1 + parse error message

Do **not** hit the real Anthropic API in tests. Use `pytest`'s `monkeypatch` to inject a fake client that returns deterministic token counts.

### 5.2 Pre-commit smoke

A simple test that runs `pytest tests/test_rules_self_application.py -q` exit-0 with current code. (The actual hook behavior is verified at commit time, not in pytest.)

## 6. Backwards compatibility

- Empty `measurements.yaml` still works (existing behavior).
- `--merge` is default-off → users explicitly opt-in to preservation.
- No analyzer signature changes. All v0.7 behavior preserved.

## 7. Versioning

`__version__ = "0.8.0"` in `tlp/__init__.py` + `pyproject.toml`.

## 8. Out of scope

- Automatic MCP server introspection (calling MCP `list_tools` to populate tools.json) — depends on MCP protocol client, separate package
- GitHub Actions CI — orthogonal; can be added later without affecting v0.8
- PyPI release — v0.9+

## 9. Open questions

- Should `count_tokens` use `system` and `messages` representative of *actual* Claude Code prompts to calibrate marginal cost more accurately? **Decision**: no for v0.8. Use minimal baseline (`system=""`, `messages=[{"role":"user","content":"x"}]`). Marginal cost of a tool def is roughly stable across baseline variations in practice; complicating UX isn't worth the second-order accuracy.
- Should output yaml include model name as metadata? **Decision**: yes. Add a top-level `model:` key so users can see which model was used. Loader ignores unknown keys.

```yaml
model: claude-opus-4-7
tools:
  mcp__pal__chat: 412
```

`load_measurements` already filters to `data.get("tools")`, so this is non-breaking.
