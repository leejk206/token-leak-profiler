# Token Leak Profiler v0.4.0 — Design Spec

- **Date**: 2026-05-29
- **Owner**: ljk9121
- **Status**: Approved (brainstorming) → ready for implementation plan
- **Builds on**: [v0.3 design](2026-05-28-token-leak-profiler-v0.3-design.md), [council deliberation](../../council/2026-05-29-cache-miss-penalty-deliberation.md)
- **Spec-checklist applied**: yes (rule 3 — self-application to existing levers)

## 1. Goal & Philosophy Shift

### Why v0.4.0

Three cycles of dogfooding (v0.3.1 council, blog comparison, this) converged on a structural finding:

**도구가 "measurement → leak"이라는 추론을 검증 없이 자동 수행 중.** 측정값 (`X tokens unused` 같은 사실)과 누수 분류 (`그러므로 누수`라는 판정)를 같은 출력 단위로 섞고 있음.

- v0.2 cache_miss_penalty: 정상 conversation extension을 누수로 분류 → false positive
- v0.3.2 cache_miss_penalty: 알고리즘 정밀화로 진짜 invalidation 검출 → 그러나 그것이 사용자가 통제 가능한지 검증 안 함
- v0.3.3 cache_turnover_cost: recoverable / architectural 분리로 한 lever 닫음
- v0.3.3 ↔ 직전 토론: 같은 결함 카테고리가 stale_context, verbose_tool_results, reasoning_overrun.dup에도 존재 — *룰을 만든 직후 한 lever에만 적용한 자기-위반*

### v0.4.0 = Philosophy 전환

> **"측정 못 하면 누수 아님; 처방 못 하면 측정도 confirmed leak 아님."**

새 룰 (이번 spec에 추가): **measurement → action 1:1**.

측정값으로부터 사용자가 *직접 실행 가능한 행동*이 1:1로 도출되지 않으면 confirmed leak으로 분류 금지. signal-only (`evidence_kind="signal"`, `confidence="low"`)로 출력.

### v0.4.0 Scope (cleanup only)

- 기존 9 sub-lever를 새 기준으로 재분류 (confirmed 3 / signal 5 / 제거 1)
- spec-checklist에 룰 5 추가
- 출력 framing 명확화
- 버전 0.3.3 → 0.4.0

### v0.4.1+ Backlog (별도 사이클)

- 신규 lever 4 (system_prompt_audit, model_choice_inefficiency, subagent_context_overdump, roundtrip_inflation) — 블로그 6 lever 정렬
- `verbose_tool_results.repeated_call` sub-case (같은 tool 같은 input 재호출 = 진짜 누수)
- Identity reframe (CLI 슬로건, lever 명칭 추가 정리)
- MCP 서버 활성화 측정

## 2. Inputs & Outputs

### Input
Unchanged from v0.3. Claude Code session transcripts.

### Output — framing 강화

**JSON:**
- `confirmed_leak_cost_usd` (의미 강화): "사용자가 직접 행동을 바꾸면 줄어드는 비용"
- `signal_attention_cost_usd` (의미 강화): "측정값이지만 사용자 통제 가능성 미확인"

**Rich table:**
- 기존 "Confirmed leak / Attention signals / Effective leak" 3-line summary 유지
- 표 위에 한 줄 추가 (dim):
  ```
  Confirmed = actionable. Signals = measurements without verified prescriptions; inspect before acting.
  ```

CLI surface 변경 없음.

## 3. Lever Re-classification

### Confirmed leak (3) — 처방 내재 확실

| Lever | Measurement | 처방 |
|---|---|---|
| `format_boilerplate` | prefix N회 반복 | "no preamble" 지시 / stop sequence — 시스템 프롬프트 변경 가능 |
| `cache_turnover_cost.recoverable` | gap ≥ 300s = TTL idle | "자리 비움 줄이기" — 직접 가능 |
| `redundant_restatement` | jaccard ≥ **0.9** (보수적, was 0.8) | "시스템 프롬프트로 이동" — 진짜 중복만 |

### Signal-only (5) — 측정값, 처방 검증 안 됨

| Lever | Measurement | 처방 검증 안 된 이유 |
|---|---|---|
| `stale_context` | block N turns 안 참조 | "참조 안 됨" ≠ "안 필요" — 사용자가 머릿속에 갖고 있을 수 있음 |
| `verbose_tool_results` | 인용률 < 10% | "인용 안 됨" ≠ "안 필요" — 결정에 쓰고 응답엔 안 옮김 가능 |
| `reasoning_overrun.dup` | 사고 중복 sentence | Claude Code에서 thinking 직접 통제권 미확인 |
| `reasoning_overrun.ratio` | thinking >> output (기존) | 이미 signal |
| `cache_turnover_cost.architectural` | gap < 300s 또는 timestamp 없음 | Claude Code 디폴트 동작, 사용자 통제 밖 |

모두 `evidence_kind="signal"`, `confidence="low"`.

### 제거 (1)

| Lever | 사유 |
|---|---|
| `tool_schema_bloat` | Claude Code transcript에 raw tool 정의 없음. v0.2 spec brainstorming에서 발견된 결함 — v0.3에서 "v0.4 deferred"로 표기. v0.4.0에서 알고리즘 redesign 없이 분석기 파일 삭제. v0.4.1+에서 다른 의미로 재정의 가능. |

## 4. Code Changes

### 4.1 Analyzer 변경

**`tlp/analyzers/stale_context.py`** — 모든 Finding 생성 시:
- `evidence_kind="signal"`
- `confidence="low"`
- suggestion 문구 변경: "compress or drop" → "candidate for review — block last referenced at turn[N], inspect if still needed before compressing"

**`tlp/analyzers/verbose_tool_results.py`** — 모든 Finding 생성 시:
- `evidence_kind="signal"`
- `confidence="low"`
- suggestion 문구 변경: "truncate or summarize" → "low citation ratio — verify result was actually used for decision-making before truncating; some output may be necessary context"

**`tlp/analyzers/reasoning_overrun.py`** — `.dup` Finding 경로:
- `evidence_kind="signal"` (was confirmed)
- `confidence="low"` (was mid)
- suggestion 문구 변경: 같은 톤 (검토 후보)

`.ratio` Finding 경로는 이미 signal/low. 변경 없음.

**`tlp/analyzers/redundant_restatement.py`** — config 키 변경만:
- `jaccard_threshold` default 0.8 → **0.9**
- "high" confidence threshold: 0.95 → 0.95 (그대로)

**`tlp/analyzers/cache_turnover_cost.py`** — architectural Finding:
- `evidence_kind="signal"` (was confirmed)
- `confidence="low"` (was mid 또는 high)
- recoverable Finding은 그대로 confirmed/mid|high

**`tlp/analyzers/tool_schema_bloat.py`** — 파일 삭제.

### 4.2 Registry 변경

**`tlp/analyzers/__init__.py`** — import 리스트에서 `tool_schema_bloat` 제거.

**`tlp/types.py`** — `LeverCategory.TOOL_SCHEMA_BLOAT` enum value 제거.

### 4.3 Config 변경

**`tlp/config/defaults.yaml`:**
- `tool_schema_bloat:` 블록 삭제
- `redundant_restatement.jaccard_threshold: 0.8 → 0.9` (v0.3.3 까지 0.8)

### 4.4 Reporter 변경 — framing

**`tlp/reporter/table.py`** — 두 군데 한 줄 추가:

요약 표 위에:
```
console.print(
    "[dim]Confirmed = actionable. Signals = measurements without verified prescriptions; inspect before acting.[/dim]"
)
```

`Confirmed leak:` 라인 description 강화:
- Was: "(content-based measurement)"
- New: "(actionable — direct prescription verified)"

`Attention signals:` 라인 description 강화:
- Was: "(high thinking-ratio etc., not proven waste)"
- New: "(measurements without verified prescriptions — inspect before acting)"

**`tlp/reporter/json_renderer.py`** — 변경 없음 (JSON 키 의미만 spec/README에 명시).

## 5. Test Changes

### v0.3.3 회귀
118 tests 중 변경 영향 받는 항목:

- `tests/test_analyzers/test_stale_context.py`: Finding assertion 시 `evidence_kind="signal"` + `confidence="low"` 기대
- `tests/test_analyzers/test_verbose_tool_results.py`: 같은 변경
- `tests/test_analyzers/test_reasoning_overrun.py`: dup-pair 테스트 update (signal 기대)
- `tests/test_analyzers/test_redundant_restatement.py`: 기존 fixture (jaccard ≥ 0.95) 여전히 통과해야 함 — verify
- `tests/test_analyzers/test_cache_turnover_cost.py`: architectural finding signal 기대
- `tests/test_analyzers/test_tool_schema_bloat.py`: 파일 삭제
- `tests/test_types.py`: `test_lever_category_values` enum set에서 `tool_schema_bloat` 제거
- `tests/test_cli_e2e.py`: 6 analyzer 기대 (was 7)

### 신규 테스트

`tests/test_reporter.py` 확장:
- `test_table_includes_framing_warning` — "Signals are measurements without verified prescriptions" 또는 그 substring이 table 출력에 있는지 확인

## 6. Config Changes

위 §4.3 참조.

## 7. Spec-checklist Rule 5

`docs/spec-checklist.md` 끝에 추가:

```markdown
## Rule 5: Measurement → action 1:1 (v0.4.0 추가)

새 메트릭을 추가하거나 기존 메트릭의 카테고리를 정할 때, 다음 문장이 spec에 명시되어야 한다:

> "이 메트릭이 X 값을 보이면 사용자는 Y 행동을 취해서 그것을 줄일 수 있다."

Y가 일반적으로 가능하지 않으면 (예: Anthropic API 메커니즘이라 사용자 통제 밖, Claude Code 내부 동작, 의도 추론 필요), 해당 메트릭은 **confirmed leak으로 분류 금지** — `evidence_kind="signal"`, `confidence="low"`로 signal-only 출력.

이 룰은 lever 추가 시 + 기존 lever 재평가 시 모두 적용. 룰 자기-적용 일관성 검증을 위한 PR-time 자동 체크는 v0.4.1 backlog.

**과거 사례:**
- v0.2 cache_miss_penalty: 정상 conversation extension 누수 분류 → 룰 5 위반 → v0.3.2/3.3 fix
- v0.3 stale_context: "참조 안 됨 = 안 필요" 가정 → 룰 5 위반 → v0.4.0 signal-only 격하
- v0.3 verbose_tool_results: "인용 안 됨 = 안 필요" 가정 → 룰 5 위반 → v0.4.0 signal-only 격하
- v0.3 reasoning_overrun.dup: thinking 통제권 미확인 → 룰 5 위반 → v0.4.0 signal-only 격하
```

## 8. Migration & Versioning

- `tlp/__init__.py`: `__version__ = "0.4.0"`
- `pyproject.toml`: `version = "0.4.0"` (sync — v0.2 교훈)
- README.md:
  - lever 표 update (tool_schema_bloat 제거, confirmed vs signal 컬럼 추가 또는 분리 표)
  - 도구 설명 한 줄 추가:
    > "Confirmed leak은 처방 검증된 누수. Signals는 측정값이며 사용자가 검토 후 판단."

Breaking change:
- JSON output에서 `tool_schema_bloat` 리포트 사라짐. 외부 consumer 없으니 안전.
- Confirmed/signal 토큰 분포 격하로 인해 변경. consumer들에게 영향은 의미만 변할 뿐 schema 동일.

## 9. Error Handling

Unchanged from v0.3.

## 10. Testing Strategy

위 §5 참조.

회귀: v0.3.3 118 tests 중 영향 받는 약 8-12개 update, tool_schema_bloat 4 tests 삭제. 신규 1-2개 추가. 예상 총 ~110 tests.

## 11. Dependencies & Runtime

Unchanged from v0.3.

## 12. v0.4.1+ Backlog

- 신규 lever 4 (블로그 6 lever 정렬):
  - `system_prompt_audit` — `stable_prefix_tokens` (이미 측정) 위에 처방 추가
  - `model_choice_inefficiency` — `model` 필드 분석
  - `subagent_context_overdump` — subagent dispatch 시 context 크기
  - `roundtrip_inflation` — 짧은 user message N회 연속
- `verbose_tool_results.repeated_call` sub-case (이건 confirmed leak 가능 — 같은 tool 같은 input 재호출은 명확한 정보 재가져옴)
- MCP 서버 활성화 측정
- Identity reframe (CLI 슬로건, lever 명칭 추가 정리)
- 룰 5 자기-적용 자동화 (analyzer 정의에 `prescription:` 필드 의무화 → pre-commit hook)

## 13. Open Questions

- redundant_restatement threshold 0.8 → 0.9 변경이 기존 합성 fixture에서 false negative 만들지 검증 필요 (구현 중 빠르게 확인 — 기존 fixture는 jaccard=0.98 정도라 안전 추정)
- `confidence` 기존 "mid"가 일부 분석기에 있음. signal-only 격하 시 일괄 "low"로 내릴지, 일부는 "mid" 유지할지. 일관성을 위해 일괄 "low" 채택.
