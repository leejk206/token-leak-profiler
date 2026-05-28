# Token Leak Profiler — Design Spec

- **Date**: 2026-05-28
- **Owner**: ljk9121
- **Status**: Approved (brainstorming) → ready for implementation plan

## 1. Goal & Scope

### Problem
LLM 비용의 상당 부분이 "일은 안 했는데 컨텍스트에 실려 매 턴 과금되는 토큰"에서 샌다. 사용자는 총 토큰 수만 보고, 어떤 종류의 토큰이 낭비인지 모른다.

### Goal
LLM 에이전트/앱이 실제 작업에 기여하지 않는 토큰을 **6가지 lever 카테고리로 분류 측정**하고, 각 누수에 대해 **actionable suggestion**을 제공하는 CLI 도구.

### v1 Non-Goals
- 다중 세션 집계/대시보드 (`tlp aggregate`는 v2).
- 라이브 API 호출 가로채기 (Claude Code 세션 로그 post-hoc 분석만).
- 절감 시뮬레이션 (suggestion 적용 시 절감량 추정은 v2).
- Markdown/HTML 리포트 (CLI 표 + JSON만).
- Anthropic 외 provider (OpenAI/Gemini 어댑터는 v2+).

## 2. Inputs & Outputs

### Input
- Claude Code 세션 transcript JSONL.
- 경로: `~/.claude/projects/<slug>/*.jsonl` 또는 임의 경로.
- 한 line = 한 event (user message / assistant message / tool_result / system).
- 파서는 비공식 포맷 변동을 어댑터 레이어에서 흡수한다.

### Output (v1)
1. **Default (rich CLI 표)**: lever별 토큰·비용·% bar + finding top-N.
2. **`--format json`**: 머신리더블 LeakReport 배열.
3. Exit codes: `0` 정상, `1` 사용자 에러(파일 없음/스키마 불일치), `2` 내부 에러.

## 3. Architecture

Approach B: Registry + ParsedTrace.

```
token-leak-profiler/
  pyproject.toml
  tlp/
    __init__.py
    cli.py                      # typer entry
    parser/
      __init__.py
      claude_code.py            # transcript.jsonl → ParsedTrace
    types.py                    # ParsedTrace, Turn, Block, Usage, LeakReport, Finding 등 dataclass
    analyzers/
      __init__.py               # 모든 analyzer auto-import → __init_subclass__ 등록
      base.py                   # BaseAnalyzer + LeverCategory enum + registry
      stale_context.py
      redundant_restatement.py
      tool_schema_bloat.py
      verbose_tool_results.py
      reasoning_overrun.py
      format_boilerplate.py
    tokenizer/
      __init__.py
      local.py                  # 로컬 근사 (char/4 또는 tiktoken cl100k 근사)
      verify.py                 # anthropic count_tokens API (옵션)
    reporter/
      __init__.py
      table.py                  # rich
      json.py
    config/
      defaults.yaml             # 분석기별 임계값
      pricing.yaml              # Claude Sonnet 4.6 기본 단가
  tests/
    fixtures/
      synthetic/                # 손으로 만든 5~10턴 JSONL
      real/                     # 실제 Claude Code transcript (sanitize 됨)
    golden/                     # snapshot 결과
    test_parser.py
    test_analyzers/<lever>.py   # 분석기별 유닛 테스트
    test_e2e.py
  docs/superpowers/specs/
    2026-05-28-token-leak-profiler-design.md
```

### 데이터 흐름
1. `cli.py`가 transcript 경로 인자를 받는다.
2. `parser.claude_code.parse(path)` → `ParsedTrace` (정규화된 read-only).
3. `analyzers` 패키지 import 시점에 `__init_subclass__`로 모든 `BaseAnalyzer` 하위 클래스가 registry에 등록.
4. 각 분석기에 `ParsedTrace`를 넘겨 `LeakReport` 수집 (분석기 한 개 크래시는 다른 분석기를 막지 않는다 — try/except 격리).
5. `reporter`가 lever별 토큰을 `pricing.yaml`과 곱해 비용 환산 후 출력.

## 4. Data Model

```python
@dataclass(frozen=True)
class ParsedTrace:
    session_id: str
    turns: list[Turn]
    tool_defs: dict[str, ToolDef]   # 등장한 모든 tool 정의 (이름→스키마+토큰)
    pricing: PricingTable

@dataclass(frozen=True)
class Turn:
    index: int                       # 0-based
    role: Literal["user","assistant","tool_result"]
    blocks: list[Block]
    usage: Usage | None              # assistant turn에만 채워짐

@dataclass(frozen=True)
class Block:
    kind: Literal["text","tool_use","tool_result","thinking"]
    text: str | None
    tool_name: str | None
    tool_input: dict | None
    tool_use_id: str | None
    tokens: int                      # local approx

@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

@dataclass(frozen=True)
class ToolDef:
    name: str
    schema_json: dict
    tokens: int                      # 정의 자체의 토큰
```

분석기 컨트랙트:

```python
class LeverCategory(Enum):
    STALE_CONTEXT = "stale_context"
    REDUNDANT_RESTATEMENT = "redundant_restatement"
    TOOL_SCHEMA_BLOAT = "tool_schema_bloat"
    VERBOSE_TOOL_RESULTS = "verbose_tool_results"
    REASONING_OVERRUN = "reasoning_overrun"
    FORMAT_BOILERPLATE = "format_boilerplate"

class BaseAnalyzer:
    name: ClassVar[str]
    lever: ClassVar[LeverCategory]
    usage_bucket: ClassVar[Literal["input","output","cache_read","cache_creation"]]

    def analyze(self, trace: ParsedTrace, config: dict) -> LeakReport: ...

    def __init_subclass__(cls, **kw): registry.register(cls)

@dataclass
class LeakReport:
    analyzer: str
    lever: LeverCategory
    leaked_tokens: int
    leaked_cost_usd: float            # reporter가 채움
    findings: list[Finding]

@dataclass
class Finding:
    location: str                     # "turn[7].blocks[2]"
    leaked_tokens: int
    confidence: Literal["low","mid","high"]
    suggestion: str
    evidence: dict                    # 분석기별 raw 근거 (JSON 직렬화 가능)
```

## 5. 6개 Analyzer 알고리즘

전부 `usage_bucket`을 명시해 reporter가 올바른 단가로 환산할 수 있게 한다.

### 5.1 stale_context  (bucket: input)
- 각 turn block에 대해 "마지막으로 후속 turn의 텍스트에서 substring/3-gram match된 turn 번호"를 추적.
- `last_ref + N` turn 이후에도 컨텍스트에 남아있으면 stale로 카운트. `N` 기본 5 (config).
- 누수 토큰 = (stale block tokens) × (cache-miss 횟수). 단순화를 위해 v1은 stale block 토큰을 그대로 보고하고 cache 효과 보정은 v2.
- Finding: "turn[3..7]은 turn 12 이후 참조 없음 → 압축/제거 후보".

### 5.2 redundant_restatement  (bucket: input)
- 모든 user/assistant text block을 5-gram MinHash로 LSH (datasketch).
- 자카드 유사도 ≥ 임계값 (기본 0.8) 쌍을 redundant.
- 누수 토큰 = 중복 쌍에서 더 늦게 나온 쪽의 토큰.
- Finding: "turn[5,11,19]의 도입부 4문장 동일 → 시스템 프롬프트로 이동".

### 5.3 tool_schema_bloat  (bucket: input)
- `trace.tool_defs` 토큰 합 vs 실제 turn에서 호출된 `tool_name` 집합의 정의 토큰.
- 호출 안 된 정의 = bloat. 누수 토큰 = (안 쓰인 정의 토큰) × (turn 수)  (스키마는 매 turn 재발송 가정; cache_creation/cache_read는 reporter에서 보정).
- Finding: "툴 X,Y,Z는 전 세션 0회 호출 → 정의 제거 후보 (-N tok/turn)".

### 5.4 verbose_tool_results  (bucket: input)
- 각 `tool_result` block 텍스트 → 후속 N turn(기본 3)의 text block에 3-gram substring 매칭.
- 매칭 토큰 / 결과 토큰 < 임계값 (기본 0.10) 이면 over-verbose.
- 누수 토큰 = result tokens × (1 - 매칭률).
- Finding: "turn[4] tool_result(1200토큰) 중 80토큰만 후속 인용 → 결과 truncate".

### 5.5 reasoning_overrun  (bucket: output)
- 각 assistant turn에서 thinking block 토큰 vs 같은 turn의 text block 토큰.
- thinking 내 sentence(`. ! ?` split)에서 5-gram MinHash로 중복 sentence 쌍 탐지.
- 누수 = 중복 sentence 토큰 + (thinking 토큰 > N × text 토큰일 때 초과분, N 기본 5).
- Finding: "turn[7] thinking 2400토큰, 중복 sentence 3쌍 → max_thinking_tokens 하향".

### 5.6 format_boilerplate  (bucket: output)
- 모든 assistant text block의 첫·마지막 K(기본 80) 토큰에서 다른 turn과 공통 prefix/suffix를 LCS로 추출.
- 3턴 이상에 동일 prefix/suffix가 등장하면 boilerplate.
- 누수 = boilerplate 토큰 × 등장 횟수 (첫 1회는 제외).
- Finding: "응답 머리말 '알겠습니다, ...'가 12회 반복 → 시스템 프롬프트로 흡수".

## 6. CLI Surface

```
tlp analyze <path-to-transcript.jsonl> [options]

Options:
  --format {table,json}              default: table
  --output PATH                      json을 파일에 저장
  --config PATH                      defaults.yaml override
  --pricing PATH                     pricing.yaml override
  --analyzers a,b,c                  특정 분석기만 (기본 전체 6)
  --verify                           anthropic count_tokens로 총 토큰 검증, drift 표시
  --min-confidence {low,mid,high}    표시할 finding 최소 신뢰도 (기본 mid)
  --strict                           파싱 에러 발생 시 abort (기본은 warn + skip)
```

### Table 출력 구조
1. 헤더: `Session <id> · <turns>turns · <total_tokens>tok · $<total_cost>`.
2. **Top-line**: lever별 한 줄 — `<lever> | <tokens> | $<cost> | <%>bar`.
3. **Total leak estimate**: 6개 합. 단, lever 간 누수가 일부 겹칠 수 있어 "추정 상한"임을 명시.
4. **Findings**: lever별 top-N (기본 5). location · tokens · confidence · suggestion 1줄.

### JSON 스키마 (요약)
```json
{
  "session_id": "...",
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "total_cost_usd": 0.0,
  "reports": [
    {
      "analyzer": "stale_context",
      "lever": "stale_context",
      "leaked_tokens": 0,
      "leaked_cost_usd": 0.0,
      "findings": [{"location":"...","leaked_tokens":0,"confidence":"mid","suggestion":"...","evidence":{}}]
    }
  ],
  "tokenizer": {"mode":"local","verify_drift_pct":null}
}
```

## 7. Tokenizer 전략

- 기본: 로컬 근사. v1 구현은 단순 `len(text) / 4` (또는 tiktoken `cl100k_base`) — 분석기는 상대량만 보면 되므로 근사로 충분.
- `--verify`: `anthropic.Anthropic().beta.messages.count_tokens(...)`로 turn별 정확 토큰 받아와서 로컬 근사와 비교. drift > 5%면 경고. 검증만, 분석기 결과는 여전히 로컬 기준.
- 네트워크 실패 / API 키 없음 → warn 후 verify skip.

## 8. Pricing

- `config/pricing.yaml` (Claude Sonnet 4.6 기본):
  ```yaml
  models:
    claude-sonnet-4-6:
      input_per_mtok: 3.00
      output_per_mtok: 15.00
      cache_read_per_mtok: 0.30
      cache_creation_per_mtok: 3.75
  default: claude-sonnet-4-6
  ```
- 분석기는 토큰 + `usage_bucket`만 보고. reporter가 곱셈.
- `--pricing` 으로 사용자 yaml 주입 가능.

## 9. Config & Defaults

`config/defaults.yaml`:
```yaml
stale_context:
  stale_after_turns: 5
redundant_restatement:
  jaccard_threshold: 0.8
  ngram: 5
verbose_tool_results:
  citation_ratio_threshold: 0.10
  followup_window_turns: 3
reasoning_overrun:
  thinking_to_output_ratio: 5
  sentence_ngram: 5
format_boilerplate:
  edge_window_tokens: 80
  min_repetition: 3
report:
  findings_per_lever: 5
  min_confidence: mid
```

CLI `--config` 으로 override.

## 10. 에러 처리

- **파싱 실패** (깨진 JSON line, 알 수 없는 event 타입): 해당 line skip, warning 카운트만 표시. `--strict`면 abort with exit 1.
- **분석기 예외**: try/except로 lever 격리. 해당 lever는 finding 0개 + `"error": "..."` 필드로 표시.
- **빈 transcript / 0턴**: empty report, exit 0.
- **`--verify` 실패**: warn, local 결과만 보고.

## 11. 테스트 전략

- **유닛**: 분석기별 positive + negative + edge (빈 trace, 1턴, thinking 없음, tool 없음 등). 분석기당 ≥ 5케이스.
- **파서 유닛**: 합성 fixture round-trip + Claude Code 실제 sample (sanitize) 2~3개.
- **e2e**: subprocess로 `tlp analyze fixture.jsonl --format json` 실행 → JSON 스키마 + golden 비교.
- **회귀**: `tests/golden/*.json` 스냅샷, `pytest --update-golden` 토글 (pytest-snapshot 또는 syrupy).
- 커버리지 목표: 분석기 ≥ 90%, 파서 ≥ 95%.

## 12. 의존성 & 런타임

- Python ≥ 3.11.
- 패키지매니저: uv.
- 런타임 deps: `typer`, `rich`, `datasketch`, `pyyaml`.
- 옵션 deps: `anthropic` (verify mode).
- 개발 deps: `pytest`, `pytest-snapshot`, `ruff`, `mypy`.

## 13. v2+ Backlog (참고용, 구현 X)

- `tlp aggregate <dir>` — 디렉토리 합산 리포트.
- Markdown/HTML 리포트.
- Suggestion 적용 시 절감량 simulation.
- OpenAI / Gemini provider 어댑터.
- pyproject entry-points로 외부 패키지가 analyzer 등록 (Approach C로 진화).
- Live tap (Anthropic SDK middleware).
- Lever 간 누수 중복 deduplication 정밀화.

## 14. Open Questions (구현 중 결정)

- Local tokenizer: `len // 4` 단순 근사로 v1 충분한지, 첫 PR에서 tiktoken cl100k 비교 측정 후 결정.
- Claude Code transcript 포맷의 정확한 thinking block 표현 — 첫 파서 작성 시 실제 sample 확인 후 fix.
- MinHash 파라미터 (num_perm) — 256으로 시작, fixture 회귀 측정 후 조정.
