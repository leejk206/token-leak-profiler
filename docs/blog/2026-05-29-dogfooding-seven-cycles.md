# 도그푸딩 7 사이클 — 도구가 자기 자신을 어떻게 진화시켰나

> 2026-05-29 · v0.1.0에서 v0.6.1까지 토큰 누수 측정기를 만들면서, 도구가 자기 자신의 결함을 7번 발견하고 7번 닫았다. 각 사이클은 spec → plan → TDD execution → dogfooding → 결함 발견 → 패치. 패치마다 spec-checklist에 룰이 1개씩 추가됐다. portfolio-ready 시점에 도구가 가진 룰 6개와 도그푸딩이 드러낸 메타 패턴의 기록이다.

이전 글([토큰 누수 측정기 만들기](2026-05-28-token-leak-profiler-making-of.md))은 첫 ship의 두 가지 구조적 발견에서 끝났다. 그 후 다섯 번의 사이클이 더 있었다.

## 결함 패턴이 7번 반복됐다

| # | 사이클 | 발견된 결함 | 닫은 방법 |
|---|---|---|---|
| 1 | v1.1 | `message.id` consecutive 그룹핑만, non-consecutive 놓침 | 코드 fix |
| 2 | v0.2 final review | non-consecutive 더블카운팅 (1번과 같은 카테고리) | 코드 fix |
| 3 | v0.2 spec | `tool_schema_bloat`: Claude Code transcript에 raw tools 없음을 가정 안 함 | v0.4에서 lever 제거 |
| 4 | v0.3 ai-title | wire format `event.message.content` 가정, 실제는 `event.aiTitle` 최상위 | v0.3 cleanup |
| 5 | v0.3.2 cache_miss_penalty | "X > 0 = 누수" semantic 가정. 정상 conversation extension을 누수로 분류 | v0.3.3 cache_turnover_cost로 reframe |
| 6 | v0.4 cache_turnover.architectural | "사용자가 줄일 수 있는 비용"이라 가정. 실제는 Claude Code 내부 동작 | v0.4 architectural→signal 격하 |
| 7 | v0.6 mcp_server_overhead | `200 tok/tool × count` 곱셈 결과에 `confirmed` 라벨 (룰 5 자기-위반) | v0.6.1 evidence_kind 3-tier |

**같은 카테고리 결함이 7번.** 각자 다르게 보였지만 본질은 같다: *spec 작성자(나)가 가정을 검증 없이 코드로 옮긴 것*. wire format, semantic, recoverability, label honesty — 추상화 층위가 다를 뿐 모두 *검증 안 한 가정*.

## 패치마다 룰이 추가됐다

각 결함을 닫을 때 *그 카테고리의 결함이 다시 안 발생하도록* spec-checklist에 룰을 1개씩 추가했다.

```markdown
# docs/spec-checklist.md (v0.6.1 기준)

Rule 1: Field-level discovery (v0.3.1)
  → 새 분석기 spec 작성 전, `tlp schema-dump` 실행해 event/field 구조 확인.

Rule 2: Cache-aware cost framing (v0.3.3)
  → input 토큰을 보고할 때 cache_read/cache_creation 단가를 명시.

Rule 3: 누수 = 사용자-recoverable (v0.3.3)
  → 사용자가 직접 행동으로 줄일 수 있어야 누수. API 메커니즘이면 signal.

Rule 4: TODO

Rule 5: Measurement → action 1:1 (v0.4)
  → 측정값에서 사용자 행동이 1:1로 도출되지 않으면 confirmed 금지.

Rule 6: Measurement vs model-output (v0.6.1)
  → leaked_tokens가 transcript 직접 추출인지, 임계값·heuristic이 곱해진 모델 출력인지.
  → 모델 출력이면 confirmed 금지, estimated 강제.
```

룰을 만든 직후 *그 룰을 새 작업에 적용 안 함*이 패턴이었다. 6번째 결함(v0.6)에선 v0.4에서 만든 룰 5를 적용 안 해서 발생. 7번째(v0.6.1)에선 룰 6을 추가하며 *그것의 자기-적용까지 명시*. 이 사이클은 닫혔지만, 8번째가 안 나오리란 보장은 못 한다.

## 도구의 정체성이 7사이클을 거치며 바뀜

**v0.1 (출시 시점):**
> "Classify wasted LLM tokens by 6 leak levers."

**v0.6.1 (현재):**
> "Measure actionable LLM token costs in Claude Code sessions. 3-tier evidence framework: confirmed (measured + actionable) / estimated (heuristic + actionable) / signal (measurement without verified prescription)."

차이의 핵심:
- "wasted tokens" → "actionable token costs" — 도구가 자의적으로 "낭비"라 단정하지 않음
- 6 lever → 10 lever (블로그 6/6 정렬: 5/6 자동 측정 + 1/6 reject)
- 2-tier (confirmed/signal) → 3-tier (estimated 추가) — 추정과 측정 사이 라벨 정직성

마지막 변화가 특히 중요하다. v0.6.1 전까지 도구는 *추정값을 confirmed로 표시*하고 있었다. 사용자(나) 의식적으로 안 했지만 spec이 그렇게 적혔고, 그게 7번째 결함의 원인이었다.

## Council 워크플로

v0.5 이후 분석기 추가 사이클에서 [council 스킬](https://github.com/superpowers/skills/tree/main/council)을 외부 모델 검증 도구로 사용했다. 3 코어 agent(Steelman / Red Team / Context Keeper)가 라운드로 토론.

v0.6.0 도그푸딩 직후 council 호출 — 사용자(나)는 한 가지 의심을 제기했다:

> "pal MCP가 unused로 잡혔는데, council Skill이 pal MCP를 indirect 사용하는 거 아닌가?"

Council Round 1 — Context Keeper가 실데이터 검증:
- `mcp__pal` 직접 호출 = 0건
- council Skill = Agent tool 기반, mcp__pal__consensus 안 부름
- **사용자 의심 반증.**

근데 *별도의* 결함을 Red Team이 발견:
- `evidence_kind="confirmed"`가 추정값(200 tok/tool × count)에 붙음 = 룰 5 자기-위반
- 새 룰 6 필요 — measurement vs model-output 구별

사용자가 *틀린 의심*을 했고, council이 *진짜 결함*을 찾았다. 이게 council의 가치 — 사용자 가정과 도구 가정 *둘 다* 검증.

## 도구가 자기 자신에 돌렸을 때

도그푸딩 결과 (v0.6.1 시점, 이번 글을 작성하는 세션 기준 1100 turns / $63):

```
Confirmed leak:    $3.62   ← measured + actionable
Estimated leak:    $0.03   ← heuristic + actionable (MCP server unused)
Attention signals: $10.07  ← measurement without verified prescription
```

- **$3.62 confirmed**: 대부분 `cache_turnover_cost.recoverable` ($3.50, TTL idle). 내가 응답하는데 5분+ 걸린 turn들.
- **$0.03 estimated**: `mcp_server_overhead` ($0.026). playwright/pal/Gmail/Calendar/Drive/vercel 6개 서버 활성화됐는데 호출 0회. settings에서 disable 가능.
- **$10.07 signals**: 대부분 `cache_turnover_cost.architectural` ($6) — Claude Code가 매 새 user turn마다 conversation history 재캐싱하는 *시스템 동작*. 사용자가 못 고침. *조사 후보*로만 표시.

이 분류 자체가 도구의 7사이클 진화의 결과다. 처음 v0.2 cache_miss_penalty가 $10을 "누수"로 보고했었을 때, 사용자가 "이거 진짜 줄일 수 있어?"라고 물었던 것이 v0.3.3 → v0.6.1까지 6번의 리프레이밍을 이끌었다.

## Portfolio publish 직전 상태

- 84 commits
- 144 tests green
- ruff/mypy clean
- 11 lever (4 confirmed + 1 estimated + 6 signal)
- 6 spec-checklist 룰
- 2 council 토론 기록
- v0.1 making-of 블로그 + 이 글
- 다른 사용자 0명 — *지금까지 사용자 = 만든 사람 1명*

마지막 줄이 핵심이다. 도구가 견고해진 만큼 *외부 가시성은 0*. 7번의 도그푸딩 사이클은 *나 혼자만* 본 것이었다.

## 외부 공개 시점에 도구가 갖는 것

1. **honest 3-tier output** — 사용자가 "내가 줄일 수 있는 것"과 "측정만 한 것"을 구별 가능.
2. **검증된 spec-checklist** — 다음 분석기 추가 시 6개 룰을 강제 적용.
3. **자기 한계 기록** — `docs/spec-checklist.md`의 "과거 사례" 섹션이 6개 결함의 *학명*을 남김.
4. **검증된 도그푸딩 패턴** — 매 사이클: ship → 실세션 분석 → 결함 발견 → 패치 + 룰 추가.

## v0.7+ 백로그 (외부 사용자가 생긴 후)

- **partial use granularity** — 서버 단위 0회 호출 vs 부분 사용. council Red Team의 Scenario B (가장 큰 실 누수가 invisible).
- **룰 자기-적용 자동화** — analyzer 정의에 `prescription:`, `measurement_basis:` 필드 의무화. pre-commit hook으로 검증. 같은 카테고리 결함 *구조적으로* 차단.
- **tool schema 실측** — Anthropic `count_tokens` API로 200 tok/tool heuristic 대체. estimated → confirmed 승급 후보.

이 셋이 v0.7. 그 후엔 진짜 *다른 사람의 사용 사례*가 도구를 바꿀 차례다.

## 마무리

도그푸딩 7사이클이 보여준 진짜 가치는 *도구 자체의 견고함*이 아니라 *결함 발견 메커니즘이 메타 룰로 축적되는 과정*이었다. 룰 1을 만들 때는 "이런 결함이 또 나올까" 모르고 적었다. 룰 6에 도달할 때쯤엔 "또 나오면 룰 7이 추가될 것"임을 안다.

같은 카테고리 결함이 8번째 안 나오면 *그건 메커니즘이 작동한 증거*. 나오면 *룰 7이 추가될 것*. 어느 쪽이든 도구는 한 발 더 정직해진다.

코드: [github.com/leejk206/token-leak-profiler](https://github.com/leejk206/token-leak-profiler)
