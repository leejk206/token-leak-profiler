# Token Leak Profiler v0.8.0 Implementation Plan

> Use subagent-driven-development. 4 tasks.

**Goal:** Pre-commit hook for rule self-application + `tlp count-tokens` CLI to populate measurements.yaml from Anthropic count_tokens API.

**Spec:** [v0.8-design.md](../specs/2026-05-29-token-leak-profiler-v0.8-design.md)

---

## Task 1: Pre-commit hook

**Files:** `.pre-commit-config.yaml` (NEW), `pyproject.toml`, `README.md`

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

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

- [ ] **Step 2: Add pre-commit dev dependency**

In `pyproject.toml`, the `[dependency-groups]` `dev` list — add `"pre-commit>=3.7"`.

```bash
uv sync --group dev
```

- [ ] **Step 3: Smoke-install hook**

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Expected: rules-self-application + ruff both pass. (Don't commit the hook activation; it's user-local. Just verify the config works.)

- [ ] **Step 4: README update**

Find a "Development" or "Contributing" section in README (or add one near the bottom). Add:

```markdown
## Contributing

Install pre-commit hooks before your first commit:

\`\`\`bash
uv sync --group dev
uv run pre-commit install
\`\`\`

The pre-commit gate enforces:
- `tests/test_rules_self_application.py` (rules 5/6 — runs only when analyzer code changes)
- `ruff check`
```

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml pyproject.toml uv.lock README.md
git commit -m "feat(ci): pre-commit hook for rule self-application + ruff"
```

---

## Task 2: count-tokens module + tests (mocked SDK)

**Files:** `tlp/measurements/__init__.py` (NEW), `tlp/measurements/count_tokens.py` (NEW), `tests/test_count_tokens.py` (NEW), `tests/fixtures/synthetic/tools_sample.json` (NEW)

- [ ] **Step 1: Create fixture `tests/fixtures/synthetic/tools_sample.json`**

```json
[
  {
    "name": "mcp__demo__simple",
    "description": "A simple demo tool",
    "input_schema": {
      "type": "object",
      "properties": {"x": {"type": "string"}},
      "required": ["x"]
    }
  },
  {
    "name": "mcp__demo__complex",
    "description": "A more elaborate demo tool with multiple parameters",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "search query"},
        "limit": {"type": "integer", "default": 10},
        "filters": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["query"]
    }
  }
]
```

- [ ] **Step 2: Create `tlp/measurements/__init__.py`**

```python
from .count_tokens import count_tool_tokens, write_measurements

__all__ = ["count_tool_tokens", "write_measurements"]
```

- [ ] **Step 3: Write failing tests `tests/test_count_tokens.py`**

```python
"""Tests for tlp.measurements.count_tokens — Anthropic SDK is mocked."""
from __future__ import annotations
from pathlib import Path
import json
import yaml
import pytest

from tlp.measurements import count_tool_tokens, write_measurements


FIX = Path(__file__).parent / "fixtures" / "synthetic" / "tools_sample.json"


class _FakeResp:
    def __init__(self, n: int):
        self.input_tokens = n


class _FakeMessages:
    def __init__(self, baseline: int, per_tool: dict[str, int]):
        self.baseline = baseline
        self.per_tool = per_tool

    def count_tokens(self, *, model, system, messages, tools):
        # Sum baseline + each tool's contribution
        total = self.baseline
        for t in tools:
            total += self.per_tool.get(t["name"], 0)
        return _FakeResp(total)


class _FakeClient:
    def __init__(self, baseline: int, per_tool: dict[str, int]):
        self.messages = _FakeMessages(baseline, per_tool)


def test_count_tool_tokens_marginal_correct():
    """count_tool_tokens returns marginal cost per tool, not absolute."""
    tools = json.loads(FIX.read_text())
    client = _FakeClient(baseline=10, per_tool={
        "mcp__demo__simple": 50,
        "mcp__demo__complex": 120,
    })
    result = count_tool_tokens(client, model="claude-opus-4-7", tools=tools)
    assert result == {
        "mcp__demo__simple": 50,
        "mcp__demo__complex": 120,
    }


def test_count_tool_tokens_empty_input():
    tools = []
    client = _FakeClient(baseline=10, per_tool={})
    result = count_tool_tokens(client, model="claude-opus-4-7", tools=tools)
    assert result == {}


def test_write_measurements_overwrite(tmp_path):
    """Without --merge, write_measurements replaces tools mapping wholesale."""
    target = tmp_path / "m.yaml"
    target.write_text(yaml.safe_dump({"tools": {"old_tool": 999}}))
    write_measurements(target, {"new_tool": 50}, model="claude-opus-4-7", merge=False)
    loaded = yaml.safe_load(target.read_text())
    assert loaded["tools"] == {"new_tool": 50}
    assert loaded["model"] == "claude-opus-4-7"


def test_write_measurements_merge_preserves(tmp_path):
    """With --merge, write_measurements preserves existing keys not in input."""
    target = tmp_path / "m.yaml"
    target.write_text(yaml.safe_dump({"tools": {"old_tool": 999, "shared": 10}}))
    write_measurements(target, {"shared": 50, "new_tool": 75}, model="claude-opus-4-7", merge=True)
    loaded = yaml.safe_load(target.read_text())
    assert loaded["tools"] == {"old_tool": 999, "shared": 50, "new_tool": 75}


def test_write_measurements_new_file(tmp_path):
    """Writes a fresh file if target doesn't exist."""
    target = tmp_path / "fresh.yaml"
    write_measurements(target, {"a": 10}, model="claude-opus-4-7", merge=False)
    loaded = yaml.safe_load(target.read_text())
    assert loaded == {"model": "claude-opus-4-7", "tools": {"a": 10}}


def test_load_measurements_still_works_with_model_key(tmp_path):
    """Existing load_measurements ignores top-level 'model' key — backward compat."""
    from tlp.config import load_measurements
    target = tmp_path / "m.yaml"
    target.write_text(yaml.safe_dump({
        "model": "claude-opus-4-7",
        "tools": {"a": 10, "b": 20},
    }))
    assert load_measurements(target) == {"a": 10, "b": 20}
```

- [ ] **Step 4: Run failing**

```bash
uv run pytest tests/test_count_tokens.py -v
```

Expected: FAIL with ImportError for `tlp.measurements`.

- [ ] **Step 5: Implement `tlp/measurements/count_tokens.py`**

```python
"""Anthropic count_tokens wrapper for populating measurements.yaml."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Protocol

import yaml


class _ClientLike(Protocol):
    messages: Any


_BASELINE_MESSAGES = [{"role": "user", "content": "x"}]
_BASELINE_SYSTEM = ""


def count_tool_tokens(
    client: _ClientLike,
    *,
    model: str,
    tools: list[dict],
) -> dict[str, int]:
    """Return per-tool marginal token cost.

    Marginal = count(system, messages, [tool]) - count(system, messages, []).
    Calls Anthropic count_tokens API once per tool + once for baseline.
    """
    if not tools:
        return {}

    baseline = client.messages.count_tokens(
        model=model,
        system=_BASELINE_SYSTEM,
        messages=_BASELINE_MESSAGES,
        tools=[],
    ).input_tokens

    result: dict[str, int] = {}
    for tool in tools:
        name = tool["name"]
        with_tool = client.messages.count_tokens(
            model=model,
            system=_BASELINE_SYSTEM,
            messages=_BASELINE_MESSAGES,
            tools=[tool],
        ).input_tokens
        result[name] = with_tool - baseline
    return result


def write_measurements(
    target: Path,
    tools: dict[str, int],
    *,
    model: str,
    merge: bool,
) -> None:
    """Write measurements to YAML.

    merge=True: preserve existing tool keys not in `tools` dict.
    merge=False: replace tools mapping wholesale.
    Always sets top-level `model` key.
    """
    existing_tools: dict[str, int] = {}
    if merge and target.exists():
        data = yaml.safe_load(target.read_text()) or {}
        existing_tools = dict(data.get("tools") or {})
    merged = {**existing_tools, **tools} if merge else dict(tools)
    payload = {"model": model, "tools": merged}
    target.write_text(yaml.safe_dump(payload, sort_keys=True))
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_count_tokens.py -v
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tlp/measurements/ tests/test_count_tokens.py tests/fixtures/synthetic/tools_sample.json
git commit -m "feat(measurements): count_tool_tokens + write_measurements (mocked SDK tests)"
```

---

## Task 3: CLI subcommand `tlp count-tokens`

**Files:** `tlp/cli.py`, `tests/test_cli_e2e.py`

- [ ] **Step 1: Read current `tlp/cli.py`**

Identify how other subcommands are registered (likely Typer). Find existing subcommands (`analyze`, `schema-dump`, `aggregate`) for pattern.

- [ ] **Step 2: Add `count_tokens` subcommand**

```python
@app.command("count-tokens")
def count_tokens(
    tools: Path = typer.Option(..., "--tools", "-t", exists=True,
                                help="JSON file of Anthropic-format tool definitions"),
    output: Path = typer.Option(
        Path(__file__).parent / "config" / "measurements.yaml",
        "--output", "-o",
        help="Target measurements.yaml (default: tlp/config/measurements.yaml)",
    ),
    model: str = typer.Option("claude-opus-4-7", "--model",
                               help="Anthropic model id used by count_tokens API"),
    merge: bool = typer.Option(False, "--merge",
                                help="Merge into existing measurements (default: overwrite)"),
) -> None:
    """Populate measurements.yaml via Anthropic count_tokens API."""
    import json as _json
    import os as _os

    if not _os.environ.get("ANTHROPIC_API_KEY"):
        typer.echo("ANTHROPIC_API_KEY not set; required for tlp count-tokens", err=True)
        raise typer.Exit(1)

    try:
        import anthropic
    except ImportError:
        typer.echo("anthropic SDK not installed; uv sync --extra verify", err=True)
        raise typer.Exit(1)

    try:
        tool_defs = _json.loads(tools.read_text())
    except _json.JSONDecodeError as e:
        typer.echo(f"Malformed tools JSON: {e}", err=True)
        raise typer.Exit(1)

    if not isinstance(tool_defs, list):
        typer.echo("tools.json must be a list of tool definitions", err=True)
        raise typer.Exit(1)

    from tlp.measurements import count_tool_tokens, write_measurements

    client = anthropic.Anthropic()
    measurements = count_tool_tokens(client, model=model, tools=tool_defs)
    write_measurements(output, measurements, model=model, merge=merge)

    typer.echo(f"Wrote {len(measurements)} tool measurements to {output}")
    for name, n in sorted(measurements.items()):
        typer.echo(f"  {name}: {n}")
```

- [ ] **Step 3: Smoke test (no API key)**

```bash
unset ANTHROPIC_API_KEY
uv run tlp count-tokens --tools tests/fixtures/synthetic/tools_sample.json 2>&1
```

Expected: exit code 1, stderr `"ANTHROPIC_API_KEY not set; required for tlp count-tokens"`.

- [ ] **Step 4: Run full suite**

```bash
uv run pytest -q
```

Expected: existing test_cli_e2e tests still green.

- [ ] **Step 5: Commit**

```bash
git add tlp/cli.py
git commit -m "feat(cli): tlp count-tokens subcommand"
```

---

## Task 4: Version + docs + push

**Files:** `tlp/__init__.py`, `pyproject.toml`, `README.md`

- [ ] **Step 1: Version bump**

`tlp/__init__.py`: `__version__ = "0.8.0"`
`pyproject.toml`: `version = "0.8.0"`

- [ ] **Step 2: README update**

Add `count-tokens` to CLI section:

````markdown
## Calibrating MCP measurements

If you have access to MCP tool definitions in Anthropic format (JSON list with `name`/`description`/`input_schema`), you can replace the 200 tok/tool heuristic with measured values:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run tlp count-tokens --tools your_tools.json --merge
```

This calls Anthropic's `count_tokens` API to compute each tool's marginal token cost and writes to `tlp/config/measurements.yaml`. With `--merge`, existing entries are preserved.

When all tools of an unused MCP server are measured, `mcp_server_overhead` Findings promote from `estimated` → `confirmed`.
````

- [ ] **Step 3: Final pytest + ruff**

```bash
uv run pytest -q
uv run ruff check .
```

Expected: all pass, ruff clean.

- [ ] **Step 4: Commit + push**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(v0.8.0): pre-commit hook + tlp count-tokens (anthropic SDK)

- .pre-commit-config.yaml: local enforcement of rule self-application + ruff
- tlp count-tokens: CLI to populate measurements.yaml from Anthropic count_tokens API
- write_measurements supports --merge to preserve existing entries
- load_measurements remains backward-compatible with top-level model: key

Closes v0.7 §14 open question (heuristic calibration path).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

## Report

Test count, version, ruff, push status, git log -5.
