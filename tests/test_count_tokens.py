"""Tests for tlp.measurements.count_tokens — Anthropic SDK is mocked."""
from __future__ import annotations
from pathlib import Path
import json
import yaml

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
        total = self.baseline
        for t in tools:
            total += self.per_tool.get(t["name"], 0)
        return _FakeResp(total)


class _FakeClient:
    def __init__(self, baseline: int, per_tool: dict[str, int]):
        self.messages = _FakeMessages(baseline, per_tool)


def test_count_tool_tokens_marginal_correct():
    """Returns marginal cost per tool (with_tool - baseline), not absolute."""
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
    client = _FakeClient(baseline=10, per_tool={})
    result = count_tool_tokens(client, model="claude-opus-4-7", tools=[])
    assert result == {}


def test_write_measurements_overwrite(tmp_path):
    """Without merge, replaces tools mapping wholesale."""
    target = tmp_path / "m.yaml"
    target.write_text(yaml.safe_dump({"tools": {"old_tool": 999}}))
    write_measurements(target, {"new_tool": 50}, model="claude-opus-4-7", merge=False)
    loaded = yaml.safe_load(target.read_text())
    assert loaded["tools"] == {"new_tool": 50}
    assert loaded["model"] == "claude-opus-4-7"


def test_write_measurements_merge_preserves(tmp_path):
    """With merge, preserves existing keys not in input; updates shared keys."""
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
