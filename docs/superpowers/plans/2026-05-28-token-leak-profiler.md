# Token Leak Profiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 세션 transcript JSONL을 받아 6개 lever 카테고리로 토큰 누수를 분류·측정·처방하는 Python CLI (`tlp analyze`).

**Architecture:** Registry + ParsedTrace. 한 번 파싱된 read-only `ParsedTrace`를 6개 `BaseAnalyzer` 하위 클래스가 query, 각각 `LeakReport(findings)` 반환. Reporter가 lever별 `usage_bucket`과 pricing.yaml로 비용 환산 후 rich 표 또는 JSON으로 출력. `__init_subclass__`로 analyzer 자동 등록 → 새 lever는 파일 하나 추가로 끝.

**Tech Stack:** Python 3.11+, uv, typer (CLI), rich (표), datasketch (MinHash LSH), pyyaml, anthropic SDK (verify 옵션), pytest + syrupy (snapshot).

**Spec:** [2026-05-28-token-leak-profiler-design.md](../specs/2026-05-28-token-leak-profiler-design.md)

---

## File Structure

```
token-leak-profiler/
  pyproject.toml                          # uv project
  README.md                               # 짧은 사용법
  tlp/
    __init__.py                           # __version__ = "0.1.0"
    cli.py                                # typer entry
    types.py                              # 모든 dataclass + LeverCategory enum
    parser/
      __init__.py                         # re-export parse()
      claude_code.py                      # transcript.jsonl → ParsedTrace
    analyzers/
      __init__.py                         # 모든 analyzer module import (auto-register)
      base.py                             # BaseAnalyzer + registry
      stale_context.py
      redundant_restatement.py
      tool_schema_bloat.py
      verbose_tool_results.py
      reasoning_overrun.py
      format_boilerplate.py
    tokenizer/
      __init__.py
      local.py                            # count_tokens(text) → int (chars/4)
      verify.py                           # anthropic count_tokens 호출 (옵션)
    reporter/
      __init__.py
      json_renderer.py                    # `json` is stdlib; 모듈명 충돌 회피
      table.py                            # rich
    config/
      __init__.py                         # load_defaults(), load_pricing()
      defaults.yaml
      pricing.yaml
  tests/
    __init__.py
    conftest.py                           # 공용 fixture
    fixtures/
      synthetic/
        minimal_trace.jsonl
        bloat_trace.jsonl
        stale_trace.jsonl
        redundant_trace.jsonl
        verbose_tool_trace.jsonl
        reasoning_trace.jsonl
        boilerplate_trace.jsonl
    test_types.py
    test_tokenizer_local.py
    test_config.py
    test_parser.py
    test_analyzers/
      __init__.py
      test_base.py
      test_stale_context.py
      test_redundant_restatement.py
      test_tool_schema_bloat.py
      test_verbose_tool_results.py
      test_reasoning_overrun.py
      test_format_boilerplate.py
    test_reporter.py
    test_cli_e2e.py
  docs/superpowers/
    specs/2026-05-28-token-leak-profiler-design.md
    plans/2026-05-28-token-leak-profiler.md
```

**Boundary rules:** analyzer는 raw JSONL을 본 적이 없다. reporter는 분석 로직을 모른다. tokenizer는 pricing을 모른다. config는 yaml만 읽는다.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `tlp/__init__.py`
- Create: `README.md`
- Create: `.gitignore`

- [ ] **Step 1: Init uv project**

Run from `/home/ljk9121/projects/token-leak-profiler/`:

```bash
uv init --package --name tlp --python 3.11
```

This creates `pyproject.toml`, `src/tlp/__init__.py`. We use flat layout (no `src/`), so move:

```bash
mv src/tlp tlp && rmdir src
```

- [ ] **Step 2: Edit pyproject.toml**

Replace `pyproject.toml` contents:

```toml
[project]
name = "tlp"
version = "0.1.0"
description = "Token Leak Profiler — classify wasted LLM tokens by 6 leak levers"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "rich>=13.7",
    "datasketch>=1.6",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
verify = ["anthropic>=0.40"]

[project.scripts]
tlp = "tlp.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "syrupy>=4.6",
    "ruff>=0.5",
    "mypy>=1.10",
    "anthropic>=0.40",
]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["tlp"]
```

- [ ] **Step 3: Write `tlp/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
.coverage
.DS_Store
```

- [ ] **Step 5: Write `README.md`**

```markdown
# tlp — Token Leak Profiler

Classify wasted LLM tokens in Claude Code session transcripts by 6 leak levers
(stale context, redundant restatement, tool schema bloat, verbose tool results,
reasoning overrun, format boilerplate).

## Usage

    tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

See `--help` for options.
```

- [ ] **Step 6: Install deps**

```bash
uv sync --all-extras
```

Expected: green install, `.venv/` created.

- [ ] **Step 7: Verify package imports**

```bash
uv run python -c "import tlp; print(tlp.__version__)"
```

Expected output: `0.1.0`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock tlp/__init__.py README.md .gitignore
git commit -m "chore: scaffold uv project with typer/rich/datasketch deps"
```

---

## Task 2: Core types

**Files:**
- Create: `tlp/types.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_types.py`

- [ ] **Step 1: Write failing test**

Create `tests/__init__.py` (empty).

Create `tests/test_types.py`:

```python
import pytest
from dataclasses import FrozenInstanceError
from tlp.types import (
    Block, Turn, Usage, ToolDef, ParsedTrace,
    LeverCategory, LeakReport, Finding, PricingTable,
)


def test_block_is_frozen():
    b = Block(kind="text", text="hi", tool_name=None, tool_input=None, tool_use_id=None, tokens=1)
    with pytest.raises(FrozenInstanceError):
        b.tokens = 2  # type: ignore[misc]


def test_turn_minimal_construction():
    t = Turn(index=0, role="user", blocks=(), usage=None)
    assert t.index == 0
    assert t.role == "user"


def test_lever_category_values():
    assert LeverCategory.STALE_CONTEXT.value == "stale_context"
    assert {c.value for c in LeverCategory} == {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
    }


def test_finding_evidence_default_dict():
    f = Finding(location="turn[0]", leaked_tokens=10, confidence="mid", suggestion="x")
    assert f.evidence == {}


def test_leak_report_construction():
    r = LeakReport(
        analyzer="x", lever=LeverCategory.STALE_CONTEXT,
        leaked_tokens=100, leaked_cost_usd=0.0, findings=[],
    )
    assert r.leaked_tokens == 100


def test_pricing_table_per_token():
    p = PricingTable(
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_read_per_mtok=0.3, cache_creation_per_mtok=3.75,
    )
    assert p.cost(1_000_000, "input") == pytest.approx(3.0)
    assert p.cost(500_000, "output") == pytest.approx(7.5)
    assert p.cost(0, "input") == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_types.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tlp.types'`.

- [ ] **Step 3: Write `tlp/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, ClassVar


class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    TOOL_SCHEMA_BLOAT = "tool_schema_bloat"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"


BlockKind = Literal["text", "tool_use", "tool_result", "thinking"]
TurnRole = Literal["user", "assistant", "tool_result"]
UsageBucket = Literal["input", "output", "cache_read", "cache_creation"]
Confidence = Literal["low", "mid", "high"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str | None
    tool_name: str | None
    tool_input: dict | None
    tool_use_id: str | None
    tokens: int


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


@dataclass(frozen=True)
class Turn:
    index: int
    role: TurnRole
    blocks: tuple[Block, ...]
    usage: Usage | None


@dataclass(frozen=True)
class ToolDef:
    name: str
    schema_json: dict
    tokens: int


@dataclass(frozen=True)
class PricingTable:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_creation_per_mtok: float

    def cost(self, tokens: int, bucket: UsageBucket) -> float:
        rates = {
            "input": self.input_per_mtok,
            "output": self.output_per_mtok,
            "cache_read": self.cache_read_per_mtok,
            "cache_creation": self.cache_creation_per_mtok,
        }
        return tokens / 1_000_000 * rates[bucket]


@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: tuple[Turn, ...]
    tool_defs: dict[str, ToolDef]
    pricing: PricingTable


@dataclass
class Finding:
    location: str
    leaked_tokens: int
    confidence: Confidence
    suggestion: str
    evidence: dict = field(default_factory=dict)


@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int
    leaked_cost_usd: float
    findings: list[Finding]
    error: str | None = None
```

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_types.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tlp/types.py tests/__init__.py tests/test_types.py
git commit -m "feat(types): core dataclasses (ParsedTrace, LeakReport, etc.)"
```

---

## Task 3: Local tokenizer

**Files:**
- Create: `tlp/tokenizer/__init__.py`
- Create: `tlp/tokenizer/local.py`
- Create: `tests/test_tokenizer_local.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_tokenizer_local.py`:

```python
from tlp.tokenizer.local import count_tokens


def test_empty_string():
    assert count_tokens("") == 0


def test_short_text():
    # chars/4 ceil — "hello" → 5 chars → 2
    assert count_tokens("hello") == 2


def test_exact_multiple_of_four():
    assert count_tokens("aaaa") == 1
    assert count_tokens("aaaaaaaa") == 2


def test_unicode_counted_by_chars_not_bytes():
    # 4 hangul chars → 1 token (chars/4)
    assert count_tokens("가나다라") == 1


def test_none_and_dict_safe():
    # Helper variant for non-string callers
    from tlp.tokenizer.local import count_tokens_of
    assert count_tokens_of(None) == 0
    assert count_tokens_of({"a": 1}) > 0  # JSON-serialized
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tokenizer_local.py -v
```

Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write `tlp/tokenizer/__init__.py`**

```python
from tlp.tokenizer.local import count_tokens, count_tokens_of

__all__ = ["count_tokens", "count_tokens_of"]
```

- [ ] **Step 4: Write `tlp/tokenizer/local.py`**

```python
"""Local token approximation: chars / 4, rounded up.

This is intentionally coarse — analyzers compare relative quantities, so absolute
accuracy isn't critical. For ground truth, use --verify mode (tokenizer.verify).
"""
from __future__ import annotations
import json
import math
from typing import Any


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def count_tokens_of(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return count_tokens(value)
    return count_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_tokenizer_local.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/tokenizer/ tests/test_tokenizer_local.py
git commit -m "feat(tokenizer): local approximation count_tokens (chars/4)"
```

---

## Task 4: Config loaders + yaml files

**Files:**
- Create: `tlp/config/__init__.py`
- Create: `tlp/config/defaults.yaml`
- Create: `tlp/config/pricing.yaml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_config.py`:

```python
from pathlib import Path
import pytest
from tlp.config import load_defaults, load_pricing
from tlp.types import PricingTable


def test_load_defaults_returns_dict_with_all_levers():
    d = load_defaults()
    assert set(d.keys()) >= {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
        "report",
    }
    assert d["stale_context"]["stale_after_turns"] == 5


def test_load_pricing_default_model():
    p = load_pricing()
    assert isinstance(p, PricingTable)
    assert p.input_per_mtok == 3.0
    assert p.output_per_mtok == 15.0


def test_load_defaults_with_override(tmp_path: Path):
    override = tmp_path / "custom.yaml"
    override.write_text("stale_context:\n  stale_after_turns: 99\n")
    d = load_defaults(override)
    assert d["stale_context"]["stale_after_turns"] == 99
    # other keys still present from base
    assert "redundant_restatement" in d


def test_load_pricing_with_override(tmp_path: Path):
    override = tmp_path / "p.yaml"
    override.write_text(
        "models:\n"
        "  claude-sonnet-4-6:\n"
        "    input_per_mtok: 99.0\n"
        "    output_per_mtok: 100.0\n"
        "    cache_read_per_mtok: 1.0\n"
        "    cache_creation_per_mtok: 2.0\n"
        "default: claude-sonnet-4-6\n"
    )
    p = load_pricing(override)
    assert p.input_per_mtok == 99.0
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write `tlp/config/defaults.yaml`**

```yaml
stale_context:
  stale_after_turns: 5
redundant_restatement:
  jaccard_threshold: 0.8
  ngram: 5
  num_perm: 256
tool_schema_bloat: {}
verbose_tool_results:
  citation_ratio_threshold: 0.10
  followup_window_turns: 3
  ngram: 3
reasoning_overrun:
  thinking_to_output_ratio: 5
  sentence_ngram: 5
  jaccard_threshold: 0.85
format_boilerplate:
  edge_window_tokens: 80
  min_repetition: 3
report:
  findings_per_lever: 5
  min_confidence: mid
```

- [ ] **Step 4: Write `tlp/config/pricing.yaml`**

```yaml
models:
  claude-sonnet-4-6:
    input_per_mtok: 3.0
    output_per_mtok: 15.0
    cache_read_per_mtok: 0.3
    cache_creation_per_mtok: 3.75
default: claude-sonnet-4-6
```

- [ ] **Step 5: Write `tlp/config/__init__.py`**

```python
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml

from tlp.types import PricingTable

_HERE = Path(__file__).parent
_DEFAULTS_PATH = _HERE / "defaults.yaml"
_PRICING_PATH = _HERE / "pricing.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_defaults(override_path: Path | None = None) -> dict[str, Any]:
    with _DEFAULTS_PATH.open() as f:
        base = yaml.safe_load(f) or {}
    if override_path:
        with override_path.open() as f:
            ov = yaml.safe_load(f) or {}
        return _deep_merge(base, ov)
    return base


def load_pricing(override_path: Path | None = None, model: str | None = None) -> PricingTable:
    path = override_path or _PRICING_PATH
    with path.open() as f:
        data = yaml.safe_load(f)
    model_id = model or data["default"]
    m = data["models"][model_id]
    return PricingTable(
        input_per_mtok=float(m["input_per_mtok"]),
        output_per_mtok=float(m["output_per_mtok"]),
        cache_read_per_mtok=float(m["cache_read_per_mtok"]),
        cache_creation_per_mtok=float(m["cache_creation_per_mtok"]),
    )
```

- [ ] **Step 6: Run test to verify pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add tlp/config/ tests/test_config.py
git commit -m "feat(config): defaults.yaml + pricing.yaml loaders with deep-merge override"
```

---

## Task 5: Synthetic fixture + parser

**Files:**
- Create: `tests/fixtures/synthetic/minimal_trace.jsonl`
- Create: `tlp/parser/__init__.py`
- Create: `tlp/parser/claude_code.py`
- Create: `tests/test_parser.py`

The parser reads Claude Code's JSONL transcript format. Each line is a JSON object with `type` ∈ {`user`, `assistant`, `system`, `summary`} and a nested `message` payload that mirrors the Anthropic Messages API shape. We support user/assistant types; system/summary lines are skipped (counted as warnings).

- [ ] **Step 1: Write a minimal synthetic fixture**

Create `tests/fixtures/synthetic/minimal_trace.jsonl` (each line is one JSON object — no trailing comma, no wrapping array):

```jsonl
{"type":"user","sessionId":"sess-1","uuid":"u1","timestamp":"2026-05-28T00:00:00Z","message":{"role":"user","content":"Hello there, can you help with X?"}}
{"type":"assistant","sessionId":"sess-1","uuid":"a1","timestamp":"2026-05-28T00:00:01Z","message":{"role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"Sure, I can help."}],"usage":{"input_tokens":120,"output_tokens":6,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"sess-1","uuid":"u2","timestamp":"2026-05-28T00:00:02Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"42"}]}}
```

- [ ] **Step 2: Write failing test**

Create `tests/test_parser.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.types import ParsedTrace

FIX = Path(__file__).parent / "fixtures" / "synthetic" / "minimal_trace.jsonl"


def test_parse_returns_parsed_trace():
    t = parse(FIX)
    assert isinstance(t, ParsedTrace)
    assert t.session_id == "sess-1"


def test_parse_turn_count_and_roles():
    t = parse(FIX)
    assert len(t.turns) == 3
    assert [tr.role for tr in t.turns] == ["user", "assistant", "tool_result"]


def test_parse_assistant_usage_populated():
    t = parse(FIX)
    a = t.turns[1]
    assert a.usage is not None
    assert a.usage.input_tokens == 120
    assert a.usage.output_tokens == 6


def test_parse_user_text_to_text_block():
    t = parse(FIX)
    u0 = t.turns[0]
    assert len(u0.blocks) == 1
    assert u0.blocks[0].kind == "text"
    assert u0.blocks[0].text == "Hello there, can you help with X?"
    assert u0.blocks[0].tokens > 0


def test_parse_tool_result_block():
    t = parse(FIX)
    tr = t.turns[2]
    assert tr.role == "tool_result"
    assert tr.blocks[0].kind == "tool_result"
    assert tr.blocks[0].tool_use_id == "toolu_1"
    assert tr.blocks[0].text == "42"
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 4: Write `tlp/parser/__init__.py`**

```python
from tlp.parser.claude_code import parse

__all__ = ["parse"]
```

- [ ] **Step 5: Write `tlp/parser/claude_code.py`**

```python
"""Claude Code transcript JSONL parser.

Format (informally observed): each line is one event with top-level fields
`type`, `sessionId`, `uuid`, `timestamp`, `message`. The nested `message`
mirrors the Anthropic Messages API shape: string content for user text,
list-of-blocks for richer payloads. tool_result blocks appear in user-role
messages; we split those into their own ParsedTrace turns (role="tool_result")
so analyzers can target tool I/O directly.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from tlp.types import (
    ParsedTrace, Turn, Block, Usage, ToolDef, PricingTable,
)
from tlp.tokenizer import count_tokens, count_tokens_of
from tlp.config import load_pricing


def parse(path: Path, *, pricing: PricingTable | None = None, strict: bool = False) -> ParsedTrace:
    pricing = pricing or load_pricing()
    session_id = ""
    turns: list[Turn] = []
    tool_defs: dict[str, ToolDef] = {}
    warnings: list[str] = []
    next_index = 0

    for raw_line, line_no in _iter_lines(path):
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as e:
            msg = f"line {line_no}: bad JSON: {e}"
            if strict:
                raise ValueError(msg)
            warnings.append(msg)
            continue

        if not session_id:
            session_id = event.get("sessionId", "") or session_id

        ev_type = event.get("type")
        msg = event.get("message")
        if ev_type not in ("user", "assistant") or not isinstance(msg, dict):
            warnings.append(f"line {line_no}: skipping type={ev_type!r}")
            continue

        # Tool definitions can appear nested in assistant messages (system_tools)
        # or as top-level field on event. Capture lazily.
        for td in event.get("tools", []) or msg.get("tools", []) or []:
            name = td.get("name")
            if name and name not in tool_defs:
                tool_defs[name] = ToolDef(
                    name=name,
                    schema_json=td,
                    tokens=count_tokens_of(td),
                )

        if ev_type == "user":
            user_blocks, tool_result_blocks = _split_user_blocks(msg.get("content", ""))
            if user_blocks:
                turns.append(Turn(
                    index=next_index, role="user",
                    blocks=tuple(user_blocks), usage=None,
                ))
                next_index += 1
            if tool_result_blocks:
                turns.append(Turn(
                    index=next_index, role="tool_result",
                    blocks=tuple(tool_result_blocks), usage=None,
                ))
                next_index += 1
        else:  # assistant
            blocks = _parse_assistant_content(msg.get("content", []))
            usage = _parse_usage(msg.get("usage"))
            turns.append(Turn(
                index=next_index, role="assistant",
                blocks=tuple(blocks), usage=usage,
            ))
            next_index += 1

    return ParsedTrace(
        session_id=session_id,
        turns=tuple(turns),
        tool_defs=dict(tool_defs),
        pricing=pricing,
    )


def _iter_lines(path: Path) -> Iterator[tuple[str, int]]:
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                yield line, i


def _split_user_blocks(content) -> tuple[list[Block], list[Block]]:
    """Returns (user_text_blocks, tool_result_blocks)."""
    if isinstance(content, str):
        return [_text_block(content)], []
    user_blocks: list[Block] = []
    tool_results: list[Block] = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_result":
            inner = c.get("content")
            text = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
            tool_results.append(Block(
                kind="tool_result", text=text, tool_name=None,
                tool_input=None, tool_use_id=c.get("tool_use_id"),
                tokens=count_tokens(text),
            ))
        elif c.get("type") == "text":
            user_blocks.append(_text_block(c.get("text", "")))
    return user_blocks, tool_results


def _parse_assistant_content(content) -> list[Block]:
    blocks: list[Block] = []
    if isinstance(content, str):
        return [_text_block(content)]
    for c in content or []:
        if not isinstance(c, dict):
            continue
        ctype = c.get("type")
        if ctype == "text":
            blocks.append(_text_block(c.get("text", "")))
        elif ctype == "thinking":
            text = c.get("thinking", "") or c.get("text", "")
            blocks.append(Block(
                kind="thinking", text=text, tool_name=None,
                tool_input=None, tool_use_id=None,
                tokens=count_tokens(text),
            ))
        elif ctype == "tool_use":
            blocks.append(Block(
                kind="tool_use", text=None,
                tool_name=c.get("name"),
                tool_input=c.get("input") or {},
                tool_use_id=c.get("id"),
                tokens=count_tokens_of(c.get("input") or {}),
            ))
    return blocks


def _parse_usage(u) -> Usage | None:
    if not isinstance(u, dict):
        return None
    return Usage(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(u.get("cache_creation_input_tokens", 0) or 0),
    )


def _text_block(text: str) -> Block:
    return Block(
        kind="text", text=text, tool_name=None,
        tool_input=None, tool_use_id=None,
        tokens=count_tokens(text),
    )
```

- [ ] **Step 6: Run test to verify pass**

```bash
uv run pytest tests/test_parser.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add tlp/parser/ tests/fixtures/ tests/test_parser.py
git commit -m "feat(parser): claude code transcript jsonl → ParsedTrace"
```

---

## Task 6: BaseAnalyzer + registry

**Files:**
- Create: `tlp/analyzers/__init__.py`
- Create: `tlp/analyzers/base.py`
- Create: `tests/test_analyzers/__init__.py` (empty)
- Create: `tests/test_analyzers/test_base.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_analyzers/__init__.py` (empty).

Create `tests/test_analyzers/test_base.py`:

```python
import pytest
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.types import (
    LeverCategory, LeakReport, ParsedTrace, PricingTable,
)


@pytest.fixture
def empty_trace():
    return ParsedTrace(
        session_id="s", turns=(), tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )


def test_subclass_auto_registers():
    initial = set(registry.names())

    class _DummyA(BaseAnalyzer):
        name = "_dummy_a"
        lever = LeverCategory.STALE_CONTEXT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

    assert "_dummy_a" in registry.names()
    assert "_dummy_a" not in initial
    registry.unregister("_dummy_a")


def test_analyze_returns_leak_report(empty_trace):
    class _DummyB(BaseAnalyzer):
        name = "_dummy_b"
        lever = LeverCategory.TOOL_SCHEMA_BLOAT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=42, leaked_cost_usd=0.0, findings=[],
            )

    r = _DummyB().analyze(empty_trace, {})
    assert r.leaked_tokens == 42
    registry.unregister("_dummy_b")


def test_duplicate_name_raises():
    class _DummyC(BaseAnalyzer):
        name = "_dummy_c"
        lever = LeverCategory.STALE_CONTEXT
        usage_bucket = "input"
        def analyze(self, trace, config):
            return LeakReport(analyzer=self.name, lever=self.lever, leaked_tokens=0, leaked_cost_usd=0.0, findings=[])

    with pytest.raises(ValueError, match="duplicate"):
        class _DummyC2(BaseAnalyzer):
            name = "_dummy_c"
            lever = LeverCategory.STALE_CONTEXT
            usage_bucket = "input"
            def analyze(self, trace, config):
                return LeakReport(analyzer=self.name, lever=self.lever, leaked_tokens=0, leaked_cost_usd=0.0, findings=[])

    registry.unregister("_dummy_c")
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_base.py -v
```

Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Write `tlp/analyzers/base.py`**

```python
from __future__ import annotations
from typing import ClassVar, Any
from tlp.types import ParsedTrace, LeakReport, LeverCategory, UsageBucket


class _Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, type["BaseAnalyzer"]] = {}

    def register(self, cls: type["BaseAnalyzer"]) -> None:
        if cls.name in self._by_name:
            raise ValueError(f"duplicate analyzer name: {cls.name}")
        self._by_name[cls.name] = cls

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._by_name.keys())

    def all(self) -> list[type["BaseAnalyzer"]]:
        return [self._by_name[n] for n in self.names()]

    def get(self, name: str) -> type["BaseAnalyzer"]:
        return self._by_name[name]


registry = _Registry()


class BaseAnalyzer:
    name: ClassVar[str]
    lever: ClassVar[LeverCategory]
    usage_bucket: ClassVar[UsageBucket]

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        for attr in ("name", "lever", "usage_bucket"):
            if not hasattr(cls, attr) or getattr(cls, attr) is None:
                raise TypeError(f"{cls.__name__} missing required class attribute: {attr}")
        registry.register(cls)

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        raise NotImplementedError
```

- [ ] **Step 4: Write `tlp/analyzers/__init__.py`**

```python
"""Importing this package auto-registers all built-in analyzers."""
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.analyzers import (  # noqa: F401  (imports trigger registration)
    stale_context,
    redundant_restatement,
    tool_schema_bloat,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
)

__all__ = ["BaseAnalyzer", "registry"]
```

The 6 module imports will FAIL until Tasks 7-12. **Temporarily** make `tlp/analyzers/__init__.py` only import base:

```python
from tlp.analyzers.base import BaseAnalyzer, registry

__all__ = ["BaseAnalyzer", "registry"]
```

We'll restore the full import list at the end of Task 12.

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_base.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/ tests/test_analyzers/
git commit -m "feat(analyzers): BaseAnalyzer + auto-registering registry"
```

---

## Task 7: stale_context analyzer

Stale context: a block becomes stale `N` turns after its last reference. We approximate "reference" as 3-gram overlap between the block's text and any later turn's text. Counted only for `text`/`tool_result` blocks (tool_use schemas are bloat's concern).

**Files:**
- Create: `tlp/analyzers/stale_context.py`
- Create: `tests/fixtures/synthetic/stale_trace.jsonl`
- Create: `tests/test_analyzers/test_stale_context.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/stale_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"s-stale","uuid":"u1","message":{"role":"user","content":"Initial setup: configure xyzzy with parameter foo_bar_baz_qux."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a1","message":{"role":"assistant","content":[{"type":"text","text":"Configured xyzzy foo_bar_baz_qux."}],"usage":{"input_tokens":20,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-stale","uuid":"u2","message":{"role":"user","content":"Now talk about something completely different."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a2","message":{"role":"assistant","content":[{"type":"text","text":"Different topic content here."}],"usage":{"input_tokens":40,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-stale","uuid":"u3","message":{"role":"user","content":"Still unrelated."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a3","message":{"role":"assistant","content":[{"type":"text","text":"Still unrelated answer."}],"usage":{"input_tokens":60,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-stale","uuid":"u4","message":{"role":"user","content":"Unrelated 2."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a4","message":{"role":"assistant","content":[{"type":"text","text":"Unrelated 2 answer."}],"usage":{"input_tokens":80,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-stale","uuid":"u5","message":{"role":"user","content":"Unrelated 3."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a5","message":{"role":"assistant","content":[{"type":"text","text":"Unrelated 3 answer."}],"usage":{"input_tokens":100,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-stale","uuid":"u6","message":{"role":"user","content":"Unrelated 4."}}
{"type":"assistant","sessionId":"s-stale","uuid":"a6","message":{"role":"assistant","content":[{"type":"text","text":"Unrelated 4 answer."}],"usage":{"input_tokens":120,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

The initial "xyzzy foo_bar_baz_qux" block is referenced once (turn 1), then never again. With `stale_after_turns=5`, it should be flagged stale by turn 6+.

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_stale_context.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.stale_context import StaleContextAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "stale_trace.jsonl"


def test_initial_block_flagged_stale():
    trace = parse(FIX)
    cfg = load_defaults()
    report = StaleContextAnalyzer().analyze(trace, cfg)
    locations = [f.location for f in report.findings]
    # turn 0 (initial user) should be flagged stale by end of trace
    assert any("turn[0]" in loc for loc in locations)
    assert report.leaked_tokens > 0


def test_no_stale_in_short_trace():
    # Trace shorter than stale_after_turns should have no findings
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    short = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "user", (Block("text", "hi", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(10, 1, 0, 0)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = StaleContextAnalyzer().analyze(short, load_defaults())
    assert r.findings == []


def test_recently_referenced_not_stale():
    # build a 7-turn trace where turn 0 is referenced at turn 5
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    def t(i, role, text):
        u = Usage(10, 1, 0, 0) if role == "assistant" else None
        return Turn(i, role, (Block("text", text, None, None, None, len(text)//4 or 1),), u)
    trace = ParsedTrace(
        session_id="x",
        turns=(
            t(0, "user", "alpha bravo charlie delta echo foxtrot"),
            t(1, "assistant", "ok"),
            t(2, "user", "unrelated"),
            t(3, "assistant", "ok"),
            t(4, "user", "more unrelated"),
            t(5, "assistant", "alpha bravo charlie delta echo foxtrot again"),
            t(6, "user", "newer"),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = StaleContextAnalyzer().analyze(trace, load_defaults())
    # turn 0 was referenced at turn 5; (5 + 5) = 10 > 6, so not yet stale
    assert all("turn[0]" not in f.location for f in r.findings)
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_stale_context.py -v
```

Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 4: Write `tlp/analyzers/stale_context.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import (
    LeverCategory, LeakReport, ParsedTrace, Finding,
)


def _ngrams(text: str, n: int = 3) -> set[str]:
    text = text.lower()
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


class StaleContextAnalyzer(BaseAnalyzer):
    name = "stale_context"
    lever = LeverCategory.STALE_CONTEXT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        stale_after = int(config.get("stale_context", {}).get("stale_after_turns", 5))
        findings: list[Finding] = []
        total = 0

        # Precompute later-turn n-gram sets
        later_ngrams: list[set[str]] = [set()] * len(trace.turns)
        for i, turn in enumerate(trace.turns):
            joined = " ".join(b.text or "" for b in turn.blocks if b.kind in ("text", "tool_result", "thinking"))
            later_ngrams[i] = _ngrams(joined)

        for i, turn in enumerate(trace.turns):
            for bi, block in enumerate(turn.blocks):
                if block.kind not in ("text", "tool_result"):
                    continue
                if not block.text:
                    continue
                block_ngrams = _ngrams(block.text)
                if not block_ngrams:
                    continue
                last_ref = i
                for j in range(i + 1, len(trace.turns)):
                    # Require non-trivial overlap (>5 shared 3-grams) to count as reference
                    if len(block_ngrams & later_ngrams[j]) > 5:
                        last_ref = j
                # Number of turns the block kept living in context past its last reference
                trailing = len(trace.turns) - 1 - last_ref
                if trailing >= stale_after:
                    total += block.tokens
                    findings.append(Finding(
                        location=f"turn[{i}].blocks[{bi}]",
                        leaked_tokens=block.tokens,
                        confidence="mid",
                        suggestion=(
                            f"turn[{i}] block last referenced at turn[{last_ref}] "
                            f"({trailing} turns ago) — compress or drop"
                        ),
                        evidence={"last_ref_turn": last_ref, "trailing_turns": trailing},
                    ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_stale_context.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/stale_context.py tests/fixtures/synthetic/stale_trace.jsonl tests/test_analyzers/test_stale_context.py
git commit -m "feat(analyzers): stale_context — flag blocks unreferenced for N turns"
```

---

## Task 8: redundant_restatement analyzer

Detects pairs of text blocks with ≥0.8 Jaccard on 5-grams via MinHash LSH (datasketch).

**Files:**
- Create: `tlp/analyzers/redundant_restatement.py`
- Create: `tests/fixtures/synthetic/redundant_trace.jsonl`
- Create: `tests/test_analyzers/test_redundant_restatement.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/redundant_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"s-red","uuid":"u1","message":{"role":"user","content":"Configure the system with the following constraints: throughput must exceed one thousand requests per second and latency must stay under fifty milliseconds at the ninety ninth percentile."}}
{"type":"assistant","sessionId":"s-red","uuid":"a1","message":{"role":"assistant","content":[{"type":"text","text":"Acknowledged. Will configure for throughput above one thousand RPS and tail latency below fifty milliseconds."}],"usage":{"input_tokens":30,"output_tokens":15,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-red","uuid":"u2","message":{"role":"user","content":"Configure the system with the following constraints: throughput must exceed one thousand requests per second and latency must stay under fifty milliseconds at the ninety ninth percentile."}}
{"type":"assistant","sessionId":"s-red","uuid":"a2","message":{"role":"assistant","content":[{"type":"text","text":"Different reply."}],"usage":{"input_tokens":60,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

Turns 0 and 2 are essentially identical user messages.

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_redundant_restatement.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.redundant_restatement import RedundantRestatementAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "redundant_trace.jsonl"


def test_detects_repeated_user_message():
    trace = parse(FIX)
    r = RedundantRestatementAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    # The later occurrence (turn 2) should be flagged
    assert any("turn[2]" in f.location for f in r.findings)


def test_no_findings_when_all_unique():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    def t(i, txt):
        return Turn(i, "user" if i % 2 == 0 else "assistant",
                    (Block("text", txt, None, None, None, len(txt)//4 or 1),),
                    Usage(10, 1, 0, 0) if i % 2 else None)
    trace = ParsedTrace(
        session_id="x",
        turns=tuple(t(i, f"unique content number {i} totally distinct phrasing") for i in range(6)),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = RedundantRestatementAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_redundant_restatement.py -v
```

Expected: FAIL.

- [ ] **Step 4: Write `tlp/analyzers/redundant_restatement.py`**

```python
from __future__ import annotations
from datasketch import MinHash, MinHashLSH
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


def _ngrams(text: str, n: int = 5) -> list[bytes]:
    text = text.lower()
    if len(text) < n:
        return [text.encode("utf-8")] if text else []
    return [text[i:i + n].encode("utf-8") for i in range(len(text) - n + 1)]


def _minhash(text: str, n: int, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for g in _ngrams(text, n):
        m.update(g)
    return m


class RedundantRestatementAnalyzer(BaseAnalyzer):
    name = "redundant_restatement"
    lever = LeverCategory.REDUNDANT_RESTATEMENT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("redundant_restatement", {})
        threshold = float(c.get("jaccard_threshold", 0.8))
        ngram = int(c.get("ngram", 5))
        num_perm = int(c.get("num_perm", 256))

        # Collect (turn_index, block_index, text, tokens)
        items: list[tuple[int, int, str, int]] = []
        for ti, turn in enumerate(trace.turns):
            for bi, b in enumerate(turn.blocks):
                if b.kind != "text" or not b.text or b.tokens < 10:
                    continue
                items.append((ti, bi, b.text, b.tokens))

        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        sigs: dict[str, MinHash] = {}
        for ti, bi, text, _ in items:
            key = f"turn[{ti}].blocks[{bi}]"
            m = _minhash(text, ngram, num_perm)
            sigs[key] = m
            lsh.insert(key, m)

        seen_pairs: set[tuple[str, str]] = set()
        findings: list[Finding] = []
        total = 0
        for ti, bi, text, tokens in items:
            key = f"turn[{ti}].blocks[{bi}]"
            candidates = [c for c in lsh.query(sigs[key]) if c != key]
            for cand in candidates:
                pair = tuple(sorted((key, cand)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                jacc = sigs[key].jaccard(sigs[cand])
                if jacc < threshold:
                    continue
                # Flag the later occurrence
                later, earlier = (key, cand) if _turn_idx(key) > _turn_idx(cand) else (cand, key)
                later_tokens = next(t for ti2, bi2, _, t in items if f"turn[{ti2}].blocks[{bi2}]" == later)
                total += later_tokens
                findings.append(Finding(
                    location=later, leaked_tokens=later_tokens,
                    confidence="high" if jacc >= 0.95 else "mid",
                    suggestion=f"near-duplicate of {earlier} (jaccard={jacc:.2f}) — drop or move to system prompt",
                    evidence={"duplicate_of": earlier, "jaccard": round(jacc, 3)},
                ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )


def _turn_idx(loc: str) -> int:
    return int(loc.split("[")[1].split("]")[0])
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_redundant_restatement.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/redundant_restatement.py tests/fixtures/synthetic/redundant_trace.jsonl tests/test_analyzers/test_redundant_restatement.py
git commit -m "feat(analyzers): redundant_restatement via MinHash LSH on 5-grams"
```

---

## Task 9: tool_schema_bloat analyzer

Bloat = (unused tool def tokens) × (# assistant turns). Caching not modeled in v1.

**Files:**
- Create: `tlp/analyzers/tool_schema_bloat.py`
- Create: `tests/fixtures/synthetic/bloat_trace.jsonl`
- Create: `tests/test_analyzers/test_tool_schema_bloat.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/bloat_trace.jsonl`:

```jsonl
{"type":"user","sessionId":"s-bloat","uuid":"u1","tools":[{"name":"tool_used","description":"used tool","input_schema":{"type":"object","properties":{"x":{"type":"string"}}}},{"name":"tool_dead_one","description":"never called one","input_schema":{"type":"object","properties":{"y":{"type":"string","description":"long parameter description blah blah blah"}}}},{"name":"tool_dead_two","description":"never called two","input_schema":{"type":"object","properties":{"z":{"type":"string","description":"more long verbose param description"}}}}],"message":{"role":"user","content":"Use tool_used."}}
{"type":"assistant","sessionId":"s-bloat","uuid":"a1","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"tool_used","input":{"x":"foo"}}],"usage":{"input_tokens":50,"output_tokens":10,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-bloat","uuid":"u2","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"ok"}]}}
{"type":"assistant","sessionId":"s-bloat","uuid":"a2","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"usage":{"input_tokens":60,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_tool_schema_bloat.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.tool_schema_bloat import ToolSchemaBloatAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "bloat_trace.jsonl"


def test_flags_unused_tool_defs():
    trace = parse(FIX)
    r = ToolSchemaBloatAnalyzer().analyze(trace, load_defaults())
    flagged = {f.evidence.get("tool_name") for f in r.findings}
    assert "tool_dead_one" in flagged
    assert "tool_dead_two" in flagged
    assert "tool_used" not in flagged


def test_leaked_tokens_scale_with_assistant_turns():
    trace = parse(FIX)
    r = ToolSchemaBloatAnalyzer().analyze(trace, load_defaults())
    # 2 assistant turns × unused tool def tokens
    assert r.leaked_tokens > 0
    # The unused defs are non-trivial; ensure multiplier matches assistant_turns
    unused_tokens = sum(
        td.tokens for name, td in trace.tool_defs.items()
        if name in {"tool_dead_one", "tool_dead_two"}
    )
    assistant_turns = sum(1 for t in trace.turns if t.role == "assistant")
    assert r.leaked_tokens == unused_tokens * assistant_turns
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_tool_schema_bloat.py -v
```

Expected: FAIL.

- [ ] **Step 4: Write `tlp/analyzers/tool_schema_bloat.py`**

```python
from __future__ import annotations
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding


class ToolSchemaBloatAnalyzer(BaseAnalyzer):
    name = "tool_schema_bloat"
    lever = LeverCategory.TOOL_SCHEMA_BLOAT
    usage_bucket = "input"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        called: set[str] = set()
        assistant_turns = 0
        for turn in trace.turns:
            if turn.role == "assistant":
                assistant_turns += 1
                for b in turn.blocks:
                    if b.kind == "tool_use" and b.tool_name:
                        called.add(b.tool_name)

        findings: list[Finding] = []
        total = 0
        if assistant_turns == 0:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        for name, td in trace.tool_defs.items():
            if name in called:
                continue
            leak = td.tokens * assistant_turns
            total += leak
            findings.append(Finding(
                location=f"tool_def[{name}]",
                leaked_tokens=leak,
                confidence="high",
                suggestion=(
                    f"tool '{name}' never called across {assistant_turns} assistant turns "
                    f"— remove from tools list to save ~{td.tokens} tok per turn"
                ),
                evidence={"tool_name": name, "per_turn_tokens": td.tokens,
                          "assistant_turns": assistant_turns},
            ))

        # Sort findings by leaked_tokens desc
        findings.sort(key=lambda f: f.leaked_tokens, reverse=True)
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_tool_schema_bloat.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/tool_schema_bloat.py tests/fixtures/synthetic/bloat_trace.jsonl tests/test_analyzers/test_tool_schema_bloat.py
git commit -m "feat(analyzers): tool_schema_bloat — unused tool defs × assistant turns"
```

---

## Task 10: verbose_tool_results analyzer

Each `tool_result` block → measure 3-gram overlap with the next N(=3) turns' assistant text. If citation ratio < 10%, flag as over-verbose.

**Files:**
- Create: `tlp/analyzers/verbose_tool_results.py`
- Create: `tests/fixtures/synthetic/verbose_tool_trace.jsonl`
- Create: `tests/test_analyzers/test_verbose_tool_results.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/verbose_tool_trace.jsonl`:

```jsonl
{"type":"assistant","sessionId":"s-verbose","uuid":"a1","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_1","name":"read","input":{}}],"usage":{"input_tokens":10,"output_tokens":3,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-verbose","uuid":"u1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu plus a whole lot of other text that the assistant will not cite at all in subsequent turns making this a clear example of over-verbose tool output that wastes context tokens"}]}}
{"type":"assistant","sessionId":"s-verbose","uuid":"a2","message":{"role":"assistant","content":[{"type":"text","text":"Result received. Brief unrelated reply."}],"usage":{"input_tokens":50,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"user","sessionId":"s-verbose","uuid":"u2","message":{"role":"user","content":"What is the next step?"}}
{"type":"assistant","sessionId":"s-verbose","uuid":"a3","message":{"role":"assistant","content":[{"type":"text","text":"Proceeding with next step."}],"usage":{"input_tokens":70,"output_tokens":4,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_verbose_tool_results.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.verbose_tool_results import VerboseToolResultsAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "verbose_tool_trace.jsonl"


def test_flags_verbose_tool_result():
    trace = parse(FIX)
    r = VerboseToolResultsAnalyzer().analyze(trace, load_defaults())
    assert any(f.evidence.get("tool_use_id") == "toolu_1" for f in r.findings)
    assert r.leaked_tokens > 0


def test_no_findings_when_cited():
    # tool_result text fully echoed by next assistant turn → no leak
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    payload = "key fact alpha bravo charlie delta echo foxtrot"
    trace = ParsedTrace(
        session_id="x",
        turns=(
            Turn(0, "assistant", (Block("tool_use", None, "t", {}, "tu1", 1),), Usage(10, 1, 0, 0)),
            Turn(1, "tool_result", (Block("tool_result", payload, None, None, "tu1", len(payload)//4),), None),
            Turn(2, "assistant",
                 (Block("text", "Summary: " + payload, None, None, None, len(payload)//4),),
                 Usage(20, 5, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = VerboseToolResultsAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_verbose_tool_results.py -v
```

Expected: FAIL.

- [ ] **Step 4: Write `tlp/analyzers/verbose_tool_results.py`**

```python
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
                        confidence="mid",
                        suggestion=(
                            f"tool result ({b.tokens} tok) cited only {citation_ratio:.0%} in next "
                            f"{window} turns — truncate or summarize before sending back"
                        ),
                        evidence={
                            "tool_use_id": b.tool_use_id,
                            "citation_ratio": round(citation_ratio, 3),
                            "result_tokens": b.tokens,
                        },
                    ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_verbose_tool_results.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/verbose_tool_results.py tests/fixtures/synthetic/verbose_tool_trace.jsonl tests/test_analyzers/test_verbose_tool_results.py
git commit -m "feat(analyzers): verbose_tool_results — citation ratio of tool output"
```

---

## Task 11: reasoning_overrun analyzer

Per assistant turn: (a) thinking tokens / output tokens > `thinking_to_output_ratio` (default 5) flags the excess; (b) MinHash over thinking sentences detects redundant sentence pairs (jaccard ≥ 0.85).

**Files:**
- Create: `tlp/analyzers/reasoning_overrun.py`
- Create: `tests/fixtures/synthetic/reasoning_trace.jsonl`
- Create: `tests/test_analyzers/test_reasoning_overrun.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/reasoning_trace.jsonl`:

```jsonl
{"type":"assistant","sessionId":"s-reason","uuid":"a1","message":{"role":"assistant","content":[{"type":"thinking","thinking":"Let me think about this carefully. The user wants X. I need to consider Y. Let me think about this carefully again. The user wants X. I should output Z. Let me think about this carefully again. The user wants X."},{"type":"text","text":"Z."}],"usage":{"input_tokens":10,"output_tokens":2,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_reasoning_overrun.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.reasoning_overrun import ReasoningOverrunAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "reasoning_trace.jsonl"


def test_thinking_dwarfs_output_flagged():
    trace = parse(FIX)
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert any("turn[0]" in f.location for f in r.findings)


def test_no_thinking_no_findings():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x", turns=(
            Turn(0, "assistant", (Block("text", "hello", None, None, None, 2),),
                 Usage(10, 2, 0, 0)),
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = ReasoningOverrunAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
```

Expected: FAIL.

- [ ] **Step 4: Write `tlp/analyzers/reasoning_overrun.py`**

```python
from __future__ import annotations
import re
from datasketch import MinHash, MinHashLSH
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding
from tlp.tokenizer import count_tokens

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _ngrams(text: str, n: int) -> list[bytes]:
    text = text.lower()
    if len(text) < n:
        return [text.encode("utf-8")] if text else []
    return [text[i:i + n].encode("utf-8") for i in range(len(text) - n + 1)]


def _minhash(text: str, n: int, num_perm: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for g in _ngrams(text, n):
        m.update(g)
    return m


class ReasoningOverrunAnalyzer(BaseAnalyzer):
    name = "reasoning_overrun"
    lever = LeverCategory.REASONING_OVERRUN
    usage_bucket = "output"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("reasoning_overrun", {})
        ratio = float(c.get("thinking_to_output_ratio", 5))
        ngram = int(c.get("sentence_ngram", 5))
        jacc_t = float(c.get("jaccard_threshold", 0.85))
        num_perm = 128

        findings: list[Finding] = []
        total = 0

        for ti, turn in enumerate(trace.turns):
            if turn.role != "assistant":
                continue
            thinking_tokens = sum(b.tokens for b in turn.blocks if b.kind == "thinking")
            text_tokens = sum(b.tokens for b in turn.blocks if b.kind == "text")
            if thinking_tokens == 0:
                continue

            # Overrun: thinking >> text
            overrun = 0
            if thinking_tokens > ratio * max(text_tokens, 1):
                overrun = thinking_tokens - int(ratio * max(text_tokens, 1))

            # Redundant sentences within thinking
            dup_tokens = 0
            dup_pairs: list[tuple[str, str, float]] = []
            sents: list[str] = []
            for b in turn.blocks:
                if b.kind == "thinking" and b.text:
                    sents.extend(s.strip() for s in _SENTENCE_SPLIT.split(b.text) if s.strip())
            if len(sents) >= 2:
                lsh = MinHashLSH(threshold=jacc_t, num_perm=num_perm)
                sigs: dict[int, MinHash] = {}
                for i, s in enumerate(sents):
                    m = _minhash(s, ngram, num_perm)
                    sigs[i] = m
                    lsh.insert(str(i), m)
                seen: set[tuple[int, int]] = set()
                for i, s in enumerate(sents):
                    for cand in lsh.query(sigs[i]):
                        j = int(cand)
                        if j == i:
                            continue
                        pair = (min(i, j), max(i, j))
                        if pair in seen:
                            continue
                        seen.add(pair)
                        jacc = sigs[i].jaccard(sigs[j])
                        if jacc >= jacc_t:
                            # Charge tokens of the later sentence
                            later = sents[max(i, j)]
                            dup_tokens += count_tokens(later)
                            dup_pairs.append((sents[min(i, j)][:60], later[:60], round(jacc, 2)))

            leak = overrun + dup_tokens
            if leak <= 0:
                continue
            total += leak
            findings.append(Finding(
                location=f"turn[{ti}]",
                leaked_tokens=leak,
                confidence="mid",
                suggestion=(
                    f"thinking={thinking_tokens} tok vs output={text_tokens} tok, "
                    f"{len(dup_pairs)} duplicate sentence pair(s) — lower max_thinking_tokens"
                ),
                evidence={
                    "thinking_tokens": thinking_tokens,
                    "output_tokens": text_tokens,
                    "overrun_tokens": overrun,
                    "duplicate_pairs": dup_pairs[:5],
                },
            ))

        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/test_analyzers/test_reasoning_overrun.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add tlp/analyzers/reasoning_overrun.py tests/fixtures/synthetic/reasoning_trace.jsonl tests/test_analyzers/test_reasoning_overrun.py
git commit -m "feat(analyzers): reasoning_overrun — thinking>>output + duplicate sentences"
```

---

## Task 12: format_boilerplate analyzer

Find common prefix/suffix that repeats across ≥3 assistant text blocks. Sliding LCS on first/last K(=80) tokens.

**Files:**
- Create: `tlp/analyzers/format_boilerplate.py`
- Create: `tests/fixtures/synthetic/boilerplate_trace.jsonl`
- Create: `tests/test_analyzers/test_format_boilerplate.py`

- [ ] **Step 1: Write fixture**

`tests/fixtures/synthetic/boilerplate_trace.jsonl`:

```jsonl
{"type":"assistant","sessionId":"s-bp","uuid":"a1","message":{"role":"assistant","content":[{"type":"text","text":"알겠습니다, 요청을 처리하겠습니다. The actual answer is one."}],"usage":{"input_tokens":10,"output_tokens":15,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","sessionId":"s-bp","uuid":"a2","message":{"role":"assistant","content":[{"type":"text","text":"알겠습니다, 요청을 처리하겠습니다. The actual answer is two."}],"usage":{"input_tokens":20,"output_tokens":15,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","sessionId":"s-bp","uuid":"a3","message":{"role":"assistant","content":[{"type":"text","text":"알겠습니다, 요청을 처리하겠습니다. The actual answer is three."}],"usage":{"input_tokens":30,"output_tokens":15,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"assistant","sessionId":"s-bp","uuid":"a4","message":{"role":"assistant","content":[{"type":"text","text":"알겠습니다, 요청을 처리하겠습니다. The actual answer is four."}],"usage":{"input_tokens":40,"output_tokens":15,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
```

- [ ] **Step 2: Write failing test**

`tests/test_analyzers/test_format_boilerplate.py`:

```python
from pathlib import Path
from tlp.parser import parse
from tlp.analyzers.format_boilerplate import FormatBoilerplateAnalyzer
from tlp.config import load_defaults

FIX = Path(__file__).parent.parent / "fixtures" / "synthetic" / "boilerplate_trace.jsonl"


def test_detects_repeated_prefix():
    trace = parse(FIX)
    r = FormatBoilerplateAnalyzer().analyze(trace, load_defaults())
    assert r.leaked_tokens > 0
    assert any("알겠습니다" in f.evidence.get("pattern", "") for f in r.findings)


def test_no_findings_without_repetition():
    from tlp.types import ParsedTrace, Turn, Block, Usage, PricingTable
    trace = ParsedTrace(
        session_id="x",
        turns=tuple(
            Turn(i, "assistant",
                 (Block("text", f"completely unique reply number {i} with distinct prefix and suffix words", None, None, None, 20),),
                 Usage(10, 10, 0, 0))
            for i in range(4)
        ),
        tool_defs={}, pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )
    r = FormatBoilerplateAnalyzer().analyze(trace, load_defaults())
    assert r.findings == []
```

- [ ] **Step 3: Run test to verify fail**

```bash
uv run pytest tests/test_analyzers/test_format_boilerplate.py -v
```

Expected: FAIL.

- [ ] **Step 4: Write `tlp/analyzers/format_boilerplate.py`**

```python
from __future__ import annotations
from collections import Counter
from tlp.analyzers.base import BaseAnalyzer
from tlp.types import LeverCategory, LeakReport, ParsedTrace, Finding
from tlp.tokenizer import count_tokens


def _common_prefix(strings: list[str]) -> str:
    if not strings:
        return ""
    s_min = min(strings, key=len)
    for i, ch in enumerate(s_min):
        for s in strings:
            if s[i] != ch:
                return s_min[:i]
    return s_min


def _common_suffix(strings: list[str]) -> str:
    rev = [s[::-1] for s in strings]
    return _common_prefix(rev)[::-1]


class FormatBoilerplateAnalyzer(BaseAnalyzer):
    name = "format_boilerplate"
    lever = LeverCategory.FORMAT_BOILERPLATE
    usage_bucket = "output"

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport:
        c = config.get("format_boilerplate", {})
        window_tokens = int(c.get("edge_window_tokens", 80))
        min_rep = int(c.get("min_repetition", 3))
        window_chars = window_tokens * 4  # inverse of chars/4

        # Collect assistant text blocks
        texts: list[tuple[int, int, str]] = []  # (turn_idx, block_idx, text)
        for ti, t in enumerate(trace.turns):
            if t.role != "assistant":
                continue
            for bi, b in enumerate(t.blocks):
                if b.kind == "text" and b.text:
                    texts.append((ti, bi, b.text))

        if len(texts) < min_rep:
            return LeakReport(
                analyzer=self.name, lever=self.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
            )

        findings: list[Finding] = []
        total = 0

        # Prefix patterns: count distinct first-K-char prefixes
        prefix_buckets: Counter[str] = Counter()
        suffix_buckets: Counter[str] = Counter()
        for _, _, txt in texts:
            head = txt[:window_chars]
            tail = txt[-window_chars:]
            # Bucket by first 40 chars to group similar starts before doing LCS
            prefix_buckets[head[:40]] += 1
            suffix_buckets[tail[-40:]] += 1

        # Find groups with ≥ min_rep
        for pseed, cnt in prefix_buckets.items():
            if cnt < min_rep:
                continue
            group = [txt for _, _, txt in texts if txt.startswith(pseed)]
            common = _common_prefix(group)
            if not common.strip():
                continue
            tokens_each = count_tokens(common)
            if tokens_each == 0:
                continue
            extra_reps = cnt - 1  # first occurrence is "free"
            leak = tokens_each * extra_reps
            total += leak
            example_locs = [
                f"turn[{ti}].blocks[{bi}]"
                for ti, bi, txt in texts if txt.startswith(pseed)
            ][:3]
            findings.append(Finding(
                location=f"prefix_group({example_locs[0]}+{extra_reps})",
                leaked_tokens=leak,
                confidence="high" if cnt >= 5 else "mid",
                suggestion=(
                    f"prefix '{common.strip()[:40]}...' repeated {cnt}× — "
                    f"add 'no preamble' instruction to system prompt or use stop sequence"
                ),
                evidence={"pattern": common, "repetitions": cnt, "locations": example_locs},
            ))

        for sseed, cnt in suffix_buckets.items():
            if cnt < min_rep:
                continue
            group = [txt for _, _, txt in texts if txt.endswith(sseed)]
            common = _common_suffix(group)
            if not common.strip():
                continue
            tokens_each = count_tokens(common)
            if tokens_each == 0:
                continue
            extra_reps = cnt - 1
            leak = tokens_each * extra_reps
            total += leak
            example_locs = [
                f"turn[{ti}].blocks[{bi}]"
                for ti, bi, txt in texts if txt.endswith(sseed)
            ][:3]
            findings.append(Finding(
                location=f"suffix_group({example_locs[0]}+{extra_reps})",
                leaked_tokens=leak,
                confidence="high" if cnt >= 5 else "mid",
                suggestion=(
                    f"suffix '{common.strip()[-40:]}' repeated {cnt}× — "
                    f"add 'no trailing summary' instruction or stop sequence"
                ),
                evidence={"pattern": common, "repetitions": cnt, "locations": example_locs},
            ))

        findings.sort(key=lambda f: f.leaked_tokens, reverse=True)
        return LeakReport(
            analyzer=self.name, lever=self.lever,
            leaked_tokens=total, leaked_cost_usd=0.0, findings=findings,
        )
```

- [ ] **Step 5: Restore `tlp/analyzers/__init__.py` to import all 6**

Replace `tlp/analyzers/__init__.py`:

```python
"""Importing this package auto-registers all built-in analyzers."""
from tlp.analyzers.base import BaseAnalyzer, registry
from tlp.analyzers import (  # noqa: F401  (imports trigger registration)
    stale_context,
    redundant_restatement,
    tool_schema_bloat,
    verbose_tool_results,
    reasoning_overrun,
    format_boilerplate,
)

__all__ = ["BaseAnalyzer", "registry"]
```

- [ ] **Step 6: Run test to verify pass + full suite still green**

```bash
uv run pytest tests/test_analyzers/test_format_boilerplate.py -v
uv run pytest -v
```

Expected: 2 passed for the new file; entire suite green.

- [ ] **Step 7: Verify all 6 analyzers auto-register**

```bash
uv run python -c "import tlp.analyzers; print(sorted(tlp.analyzers.registry.names()))"
```

Expected output: `['format_boilerplate', 'redundant_restatement', 'reasoning_overrun', 'stale_context', 'tool_schema_bloat', 'verbose_tool_results']`

- [ ] **Step 8: Commit**

```bash
git add tlp/analyzers/format_boilerplate.py tlp/analyzers/__init__.py tests/fixtures/synthetic/boilerplate_trace.jsonl tests/test_analyzers/test_format_boilerplate.py
git commit -m "feat(analyzers): format_boilerplate + enable all 6 in registry"
```

---

## Task 13: JSON reporter

**Files:**
- Create: `tlp/reporter/__init__.py`
- Create: `tlp/reporter/json_renderer.py`
- Create: `tests/test_reporter.py`

- [ ] **Step 1: Write failing test**

`tests/test_reporter.py`:

```python
import json
from tlp.reporter.json_renderer import render_json
from tlp.types import (
    ParsedTrace, Turn, Block, Usage, PricingTable,
    LeakReport, LeverCategory, Finding,
)


def _trace():
    return ParsedTrace(
        session_id="sess-x",
        turns=(
            Turn(0, "user", (Block("text", "hi", None, None, None, 1),), None),
            Turn(1, "assistant", (Block("text", "ok", None, None, None, 1),),
                 Usage(100, 50, 0, 0)),
        ),
        tool_defs={},
        pricing=PricingTable(3.0, 15.0, 0.3, 3.75),
    )


def test_json_includes_session_and_totals():
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress", {})],
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"stale_context": "input"})
    data = json.loads(out)
    assert data["session_id"] == "sess-x"
    assert data["total_input_tokens"] == 100
    assert data["total_output_tokens"] == 50
    assert data["reports"][0]["analyzer"] == "stale_context"
    # 20 tok × $3 / Mtok
    assert data["reports"][0]["leaked_cost_usd"] == pytest.approx(20 * 3.0 / 1_000_000)
    assert data["total_cost_usd"] > 0


def test_json_handles_analyzer_error():
    reports = [
        LeakReport(
            analyzer="reasoning_overrun", lever=LeverCategory.REASONING_OVERRUN,
            leaked_tokens=0, leaked_cost_usd=0.0,
            findings=[], error="boom",
        ),
    ]
    out = render_json(_trace(), reports, bucket_map={"reasoning_overrun": "output"})
    data = json.loads(out)
    assert data["reports"][0]["error"] == "boom"


import pytest  # noqa: E402  (used by tests above)
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_reporter.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write `tlp/reporter/__init__.py`**

```python
from tlp.reporter.json_renderer import render_json
from tlp.reporter.table import render_table

__all__ = ["render_json", "render_table"]
```

- [ ] **Step 4: Write `tlp/reporter/json_renderer.py`**

```python
from __future__ import annotations
import json
from dataclasses import asdict
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_json(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
) -> str:
    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)

    total_cost = (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )

    rendered_reports = []
    for r in reports:
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        rendered_reports.append({
            "analyzer": r.analyzer,
            "lever": r.lever.value,
            "usage_bucket": bucket,
            "leaked_tokens": r.leaked_tokens,
            "leaked_cost_usd": cost,
            "findings": [asdict(f) for f in r.findings],
            "error": r.error,
        })

    payload = {
        "session_id": trace.session_id,
        "turn_count": len(trace.turns),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_creation_tokens": total_cache_creation,
        "total_cost_usd": total_cost,
        "tokenizer": {"mode": tokenizer_mode, "verify_drift_pct": verify_drift_pct},
        "reports": rendered_reports,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
```

- [ ] **Step 5: Write minimal `tlp/reporter/table.py` stub** (so `__init__` import doesn't fail; full impl in Task 14)

```python
from __future__ import annotations
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_table(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    findings_per_lever: int = 5,
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
) -> None:
    raise NotImplementedError("see Task 14")
```

- [ ] **Step 6: Run test to verify pass**

```bash
uv run pytest tests/test_reporter.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add tlp/reporter/ tests/test_reporter.py
git commit -m "feat(reporter): json renderer with per-lever cost calc"
```

---

## Task 14: Rich table reporter

**Files:**
- Modify: `tlp/reporter/table.py`

- [ ] **Step 1: Write failing test** (extend `tests/test_reporter.py`)

Append to `tests/test_reporter.py`:

```python
from rich.console import Console
from io import StringIO
from tlp.reporter.table import render_table


def test_table_includes_lever_rows_and_totals():
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    trace = _trace()
    reports = [
        LeakReport(
            analyzer="stale_context", lever=LeverCategory.STALE_CONTEXT,
            leaked_tokens=20, leaked_cost_usd=0.0,
            findings=[Finding("turn[0]", 20, "mid", "compress this please", {})],
        ),
        LeakReport(
            analyzer="tool_schema_bloat", lever=LeverCategory.TOOL_SCHEMA_BLOAT,
            leaked_tokens=80, leaked_cost_usd=0.0,
            findings=[Finding("tool_def[unused]", 80, "high", "drop tool", {})],
        ),
    ]
    render_table(
        trace, reports,
        bucket_map={"stale_context": "input", "tool_schema_bloat": "input"},
        console=console,
    )
    output = buf.getvalue()
    assert "sess-x" in output
    assert "stale_context" in output
    assert "tool_schema_bloat" in output
    assert "compress this please" in output
    assert "drop tool" in output
```

The existing `render_table` signature needs a `console=` kwarg. Adjust:

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_reporter.py::test_table_includes_lever_rows_and_totals -v
```

Expected: FAIL (NotImplementedError).

- [ ] **Step 3: Replace `tlp/reporter/table.py`**

```python
from __future__ import annotations
from rich.console import Console
from rich.table import Table
from rich import box
from tlp.types import ParsedTrace, LeakReport, UsageBucket


def render_table(
    trace: ParsedTrace,
    reports: list[LeakReport],
    *,
    bucket_map: dict[str, UsageBucket],
    findings_per_lever: int = 5,
    tokenizer_mode: str = "local",
    verify_drift_pct: float | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()

    total_input = sum(t.usage.input_tokens for t in trace.turns if t.usage)
    total_output = sum(t.usage.output_tokens for t in trace.turns if t.usage)
    total_cache_read = sum(t.usage.cache_read_tokens for t in trace.turns if t.usage)
    total_cache_creation = sum(t.usage.cache_creation_tokens for t in trace.turns if t.usage)
    total_cost = (
        trace.pricing.cost(total_input, "input")
        + trace.pricing.cost(total_output, "output")
        + trace.pricing.cost(total_cache_read, "cache_read")
        + trace.pricing.cost(total_cache_creation, "cache_creation")
    )

    console.rule(f"[bold]Token Leak Profile — session {trace.session_id}")
    console.print(
        f"turns: {len(trace.turns)}  ·  "
        f"input: {total_input:,}  ·  output: {total_output:,}  ·  "
        f"cost: ${total_cost:.4f}"
    )
    if verify_drift_pct is not None:
        console.print(f"[dim]tokenizer={tokenizer_mode}, verify drift {verify_drift_pct:+.1f}%[/dim]")

    # Top-line table
    summary = Table(box=box.SIMPLE_HEAVY, title="Leak by lever")
    summary.add_column("lever", style="cyan")
    summary.add_column("tokens", justify="right")
    summary.add_column("cost ($)", justify="right")
    summary.add_column("% of total", justify="right")
    total_leaked_tokens = 0
    total_leaked_cost = 0.0
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        bucket = bucket_map.get(r.analyzer, "input")
        cost = trace.pricing.cost(r.leaked_tokens, bucket)
        total_leaked_tokens += r.leaked_tokens
        total_leaked_cost += cost
        pct = (r.leaked_tokens / max(total_input + total_output, 1)) * 100
        marker = " [red]ERR[/red]" if r.error else ""
        summary.add_row(
            r.lever.value + marker,
            f"{r.leaked_tokens:,}",
            f"{cost:.4f}",
            f"{pct:.1f}%",
        )
    console.print(summary)
    console.print(
        f"[bold]Estimated total leak:[/bold] "
        f"{total_leaked_tokens:,} tok / ${total_leaked_cost:.4f} "
        f"[dim](upper bound — levers may overlap)[/dim]"
    )

    # Findings per lever
    for r in sorted(reports, key=lambda x: x.leaked_tokens, reverse=True):
        if r.error:
            console.rule(f"[yellow]{r.lever.value} — analyzer error: {r.error}[/yellow]")
            continue
        if not r.findings:
            continue
        console.rule(f"[bold cyan]{r.lever.value}[/bold cyan]")
        ftab = Table(box=box.MINIMAL, show_header=True)
        ftab.add_column("location", style="dim", overflow="fold")
        ftab.add_column("tokens", justify="right")
        ftab.add_column("conf", justify="center")
        ftab.add_column("suggestion", overflow="fold")
        for f in r.findings[:findings_per_lever]:
            ftab.add_row(f.location, f"{f.leaked_tokens:,}", f.confidence, f.suggestion)
        console.print(ftab)
```

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_reporter.py -v
```

Expected: 3 passed (2 from Task 13 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add tlp/reporter/table.py tests/test_reporter.py
git commit -m "feat(reporter): rich table with leak-by-lever summary and findings"
```

---

## Task 15: Verify mode (anthropic count_tokens)

**Files:**
- Create: `tlp/tokenizer/verify.py`
- Modify: `tests/test_tokenizer_local.py` (add verify tests)

- [ ] **Step 1: Write failing test**

Append to `tests/test_tokenizer_local.py`:

```python
from unittest.mock import MagicMock, patch


def test_verify_disabled_returns_none_drift():
    from tlp.tokenizer.verify import compute_drift_pct
    # No API key / module missing → graceful None
    with patch("tlp.tokenizer.verify._count_via_anthropic", side_effect=RuntimeError("no key")):
        assert compute_drift_pct(local_total=1000, sample_messages=[]) is None


def test_verify_returns_drift_pct():
    from tlp.tokenizer.verify import compute_drift_pct
    with patch("tlp.tokenizer.verify._count_via_anthropic", return_value=1100):
        drift = compute_drift_pct(local_total=1000, sample_messages=[{"role": "user", "content": "hi"}])
        # 1100 vs local 1000 → +10%
        assert drift == 10.0


def test_verify_zero_local_safe():
    from tlp.tokenizer.verify import compute_drift_pct
    with patch("tlp.tokenizer.verify._count_via_anthropic", return_value=0):
        assert compute_drift_pct(local_total=0, sample_messages=[]) == 0.0
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_tokenizer_local.py -v
```

Expected: FAIL on the 3 new tests with ModuleNotFoundError.

- [ ] **Step 3: Write `tlp/tokenizer/verify.py`**

```python
"""Verify-mode wrapper around anthropic.messages.count_tokens.

Network/API key failures are caught and reported as None drift so the CLI can
continue with local-only results.
"""
from __future__ import annotations


def compute_drift_pct(
    local_total: int,
    sample_messages: list[dict],
    *,
    model: str = "claude-sonnet-4-5",
) -> float | None:
    if local_total == 0:
        return 0.0
    try:
        remote = _count_via_anthropic(sample_messages, model=model)
    except Exception:
        return None
    return (remote - local_total) / local_total * 100.0


def _count_via_anthropic(messages: list[dict], *, model: str) -> int:
    from anthropic import Anthropic  # imported lazily so it stays optional
    client = Anthropic()
    resp = client.messages.count_tokens(model=model, messages=messages)
    return int(resp.input_tokens)
```

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_tokenizer_local.py -v
```

Expected: 8 passed (5 original + 3 new).

- [ ] **Step 5: Commit**

```bash
git add tlp/tokenizer/verify.py tests/test_tokenizer_local.py
git commit -m "feat(tokenizer): optional anthropic count_tokens verify mode"
```

---

## Task 16: CLI entry

**Files:**
- Create: `tlp/cli.py`
- Create: `tests/test_cli_e2e.py`

- [ ] **Step 1: Write failing test**

`tests/test_cli_e2e.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

FIX = Path(__file__).parent / "fixtures" / "synthetic" / "bloat_trace.jsonl"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tlp.cli", *args],
        capture_output=True, text=True, check=False,
    )


def test_analyze_json_output():
    r = _run("analyze", str(FIX), "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["session_id"] == "s-bloat"
    assert len(data["reports"]) == 6


def test_analyze_table_default():
    r = _run("analyze", str(FIX))
    assert r.returncode == 0
    assert "tool_schema_bloat" in r.stdout
    assert "Token Leak Profile" in r.stdout


def test_missing_file_exit_1():
    r = _run("analyze", "/nonexistent/path.jsonl")
    assert r.returncode == 1


def test_filter_analyzers():
    r = _run("analyze", str(FIX), "--format", "json", "--analyzers", "tool_schema_bloat")
    data = json.loads(r.stdout)
    assert len(data["reports"]) == 1
    assert data["reports"][0]["analyzer"] == "tool_schema_bloat"
```

- [ ] **Step 2: Run test to verify fail**

```bash
uv run pytest tests/test_cli_e2e.py -v
```

Expected: FAIL `No module named tlp.cli`.

- [ ] **Step 3: Write `tlp/cli.py`**

```python
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tlp.parser import parse
from tlp.analyzers import registry
from tlp.config import load_defaults, load_pricing
from tlp.reporter import render_table, render_json

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Claude Code transcript .jsonl"),
    format: str = typer.Option("table", "--format", help="table | json"),
    output: Optional[Path] = typer.Option(None, "--output", help="write JSON to file"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="defaults.yaml override"),
    pricing_path: Optional[Path] = typer.Option(None, "--pricing", help="pricing.yaml override"),
    analyzers: Optional[str] = typer.Option(None, "--analyzers", help="comma-separated subset"),
    verify: bool = typer.Option(False, "--verify", help="verify with anthropic count_tokens"),
    min_confidence: str = typer.Option("mid", "--min-confidence", help="low | mid | high"),
    strict: bool = typer.Option(False, "--strict", help="abort on parse errors"),
) -> None:
    if not path.exists():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=1)
    if format not in ("table", "json"):
        typer.echo(f"error: --format must be 'table' or 'json'", err=True)
        raise typer.Exit(code=1)

    try:
        pricing = load_pricing(pricing_path)
        trace = parse(path, pricing=pricing, strict=strict)
        config = load_defaults(config_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:  # internal
        typer.echo(f"internal error: {e}", err=True)
        raise typer.Exit(code=2)

    selected = registry.all()
    if analyzers:
        wanted = {n.strip() for n in analyzers.split(",")}
        selected = [a for a in selected if a.name in wanted]
        if not selected:
            typer.echo(f"error: no matching analyzers in {analyzers!r}", err=True)
            raise typer.Exit(code=1)

    conf_rank = {"low": 0, "mid": 1, "high": 2}
    min_rank = conf_rank.get(min_confidence, 1)

    reports = []
    bucket_map: dict[str, str] = {}
    for cls in selected:
        bucket_map[cls.name] = cls.usage_bucket
        try:
            r = cls().analyze(trace, config)
        except Exception as e:
            from tlp.types import LeakReport, LeverCategory
            r = LeakReport(
                analyzer=cls.name, lever=cls.lever,
                leaked_tokens=0, leaked_cost_usd=0.0, findings=[],
                error=str(e),
            )
        r.findings = [f for f in r.findings if conf_rank.get(f.confidence, 1) >= min_rank]
        reports.append(r)

    drift_pct = None
    if verify:
        from tlp.tokenizer.verify import compute_drift_pct
        sample = [
            {"role": "user", "content": (b.text or "")}
            for t in trace.turns for b in t.blocks
            if t.role == "user" and b.kind == "text"
        ][:20]  # cap to avoid runaway
        local_total = sum(t.usage.input_tokens for t in trace.turns if t.usage)
        drift_pct = compute_drift_pct(local_total, sample)

    findings_per_lever = config.get("report", {}).get("findings_per_lever", 5)

    if format == "json":
        out = render_json(
            trace, reports, bucket_map=bucket_map,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
        )
        if output:
            output.write_text(out)
        else:
            sys.stdout.write(out + "\n")
    else:
        render_table(
            trace, reports, bucket_map=bucket_map,
            findings_per_lever=findings_per_lever,
            tokenizer_mode="local", verify_drift_pct=drift_pct,
            console=Console(force_terminal=False if not sys.stdout.isatty() else None),
        )


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify pass**

```bash
uv run pytest tests/test_cli_e2e.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all green.

- [ ] **Step 6: Smoke test against a real Claude Code session**

```bash
uv run tlp analyze ~/.claude/projects/-home-ljk9121-projects/$(ls -t ~/.claude/projects/-home-ljk9121-projects/ | grep '\.jsonl$' | head -1)
```

Expected: rich table output. No traceback. If parser warns about unknown event types, that's normal (system/summary lines).

- [ ] **Step 7: Commit**

```bash
git add tlp/cli.py tests/test_cli_e2e.py
git commit -m "feat(cli): tlp analyze with --format/--analyzers/--verify/--strict"
```

---

## Task 17: End-to-end golden snapshot

**Files:**
- Modify: `tests/test_cli_e2e.py` (add golden snapshot test)
- Create: `tests/golden/bloat_trace.json` (generated)

- [ ] **Step 1: Add snapshot test**

Append to `tests/test_cli_e2e.py`:

```python
def test_e2e_golden_bloat(tmp_path: Path):
    out = tmp_path / "out.json"
    r = _run("analyze", str(FIX), "--format", "json", "--output", str(out))
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    # Stable shape assertions (avoid full snapshot since floats and tokenizer
    # approximations may drift; lock structural invariants instead).
    assert data["session_id"] == "s-bloat"
    assert data["turn_count"] == 4
    analyzer_names = {r["analyzer"] for r in data["reports"]}
    assert analyzer_names == {
        "stale_context", "redundant_restatement", "tool_schema_bloat",
        "verbose_tool_results", "reasoning_overrun", "format_boilerplate",
    }
    bloat = next(r for r in data["reports"] if r["analyzer"] == "tool_schema_bloat")
    assert bloat["leaked_tokens"] > 0
    assert all("leaked_cost_usd" in r for r in data["reports"])
    assert all("usage_bucket" in r for r in data["reports"])
```

- [ ] **Step 2: Run test to verify pass**

```bash
uv run pytest tests/test_cli_e2e.py::test_e2e_golden_bloat -v
```

Expected: 1 passed.

- [ ] **Step 3: Run full suite**

```bash
uv run pytest -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli_e2e.py
git commit -m "test(e2e): structural invariants snapshot for json output"
```

---

## Task 18: Real-transcript sanity + docs polish

**Files:**
- Modify: `README.md`
- Create: `tests/fixtures/real/.gitkeep` (placeholder)
- Modify: `tlp/parser/claude_code.py` (only if real-transcript test reveals bugs)

This task validates the parser against an actual Claude Code transcript and adjusts ONLY if the synthetic schema diverged. It does NOT add new features.

- [ ] **Step 1: Locate a real transcript**

```bash
ls ~/.claude/projects/-home-ljk9121-projects/ | grep '\.jsonl$' | head -3
```

Pick one short-ish session (<2MB).

- [ ] **Step 2: Run parser against it manually**

```bash
uv run python -c "
from pathlib import Path
from tlp.parser import parse
p = Path('REPLACE_WITH_PATH').expanduser()
t = parse(p)
print(f'session={t.session_id} turns={len(t.turns)} tool_defs={len(t.tool_defs)}')
for i, turn in enumerate(t.turns[:5]):
    print(f'  turn[{i}] role={turn.role} blocks={len(turn.blocks)} usage={turn.usage}')
"
```

Expected: prints turn count and first 5 turns without exception. If exception → fix `tlp/parser/claude_code.py` to handle the actual shape, then commit the fix with `fix(parser): handle <observed-quirk>` BEFORE proceeding.

- [ ] **Step 3: Run full CLI**

```bash
uv run tlp analyze "$(ls -t ~/.claude/projects/-home-ljk9121-projects/*.jsonl | head -1)"
```

Expected: complete rich table output. No traceback.

- [ ] **Step 4: Run JSON mode**

```bash
uv run tlp analyze "$(ls -t ~/.claude/projects/-home-ljk9121-projects/*.jsonl | head -1)" --format json | head -40
```

Expected: parseable JSON.

- [ ] **Step 5: Add `tests/fixtures/real/.gitkeep`**

```bash
mkdir -p tests/fixtures/real
touch tests/fixtures/real/.gitkeep
```

(Real sanitized fixtures are out of scope — kept as placeholder for the engineer to populate later without committing PII.)

- [ ] **Step 6: Polish README**

Replace `README.md`:

```markdown
# tlp — Token Leak Profiler

Classify wasted LLM tokens in Claude Code session transcripts by 6 leak levers
and get actionable suggestions for each leak.

## Install (dev)

    uv sync --all-extras

## Usage

    uv run tlp analyze ~/.claude/projects/<slug>/<session>.jsonl

Common flags:

    --format {table,json}        default: table
    --output PATH                write JSON to file
    --analyzers a,b,c            run only these (default: all 6)
    --verify                     compare local tokenizer to anthropic API
    --min-confidence {low,mid,high}
    --strict                     abort on parser warnings

## Levers

| name | bucket | what it catches |
|---|---|---|
| stale_context | input | message blocks unreferenced for N turns |
| redundant_restatement | input | near-duplicate text blocks (MinHash 5-gram) |
| tool_schema_bloat | input | tool defs that are never called |
| verbose_tool_results | input | tool output that's mostly never cited |
| reasoning_overrun | output | thinking >> answer + duplicate sentences |
| format_boilerplate | output | preambles/closers repeated across turns |

## Tests

    uv run pytest

## License

MIT (see LICENSE).
```

- [ ] **Step 7: Commit**

```bash
git add README.md tests/fixtures/real/.gitkeep
git commit -m "docs: README usage + add real-fixture directory placeholder"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Implemented in |
|---|---|
| §1 Goals & non-goals | Plan scope matches; v2 items explicitly deferred. |
| §2 Inputs (Claude Code JSONL) | Task 5 (parser) + Task 18 (real-transcript sanity) |
| §2 Outputs (CLI table + JSON, exit codes) | Tasks 13, 14, 16 |
| §3 Architecture (Registry + ParsedTrace) | Tasks 6, 7-12 |
| §4 Data Model (all dataclasses) | Task 2 + minor additions in Task 6 (registry) |
| §5.1-5.6 Six analyzers | Tasks 7-12 |
| §6 CLI surface (all flags) | Task 16 |
| §7 Tokenizer (local + verify) | Tasks 3, 15 |
| §8 Pricing | Task 4 (yaml + loader); applied in Tasks 13, 14 |
| §9 Defaults config | Task 4 |
| §10 Error handling (parse/analyzer/verify/empty) | Task 5 (parser strict mode), Task 16 (CLI exit codes + per-analyzer try/except) |
| §11 Testing strategy | Tasks 2-17 each ship tests; Task 17 covers e2e structural assertions |
| §12 Dependencies | Task 1 pyproject |

**Placeholder scan:** No "TBD/TODO/implement later" in any step. Every step contains exact code or exact commands. Task 18 Step 2's `REPLACE_WITH_PATH` is an interactive smoke test, not code to commit.

**Type consistency:**
- `ParsedTrace.turns: tuple[Turn, ...]` — used as immutable in all analyzers ✓
- `LeakReport.findings: list[Finding]` — mutated by CLI for confidence filter; consistent ✓
- `BaseAnalyzer.usage_bucket: ClassVar[UsageBucket]` — every analyzer in Tasks 7-12 sets it ✓
- `render_table(console=)` kwarg added in Task 14 — Task 13's stub already accepts compatible signature via Task 14's replacement ✓
- `Finding.evidence: dict = field(default_factory=dict)` — tests in Tasks 7-12 access keys with `.get` ✓

**Open Question from spec §14:** "MinHash num_perm — 256 to start" → defaults.yaml ships `num_perm: 256` (used by redundant_restatement); reasoning_overrun uses 128 (smaller sentence-level corpus, locally chosen — flagged in comments).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-token-leak-profiler.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
