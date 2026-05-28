# Council Deliberation — cache_miss_penalty v0.3.2

- **Date**: 2026-05-29
- **Topic**: v0.3.2 `cache_miss_penalty` 알고리즘 및 검출된 누수($7.86 = 2.1M tokens, 6 events)가 정직한 분류인지 검증
- **Trigger session**: af0b624f-47e6-411e-a16d-db48f2ba543d.jsonl
- **Rounds**: 2 (core 3명 × 2)
- **Verdict**: 알고리즘은 진짜 패턴 검출, 하지만 "누수" 분류는 6번째 같은 카테고리 결함

## Briefing data (모든 agent에 제공)

- 알고리즘: `expected_cr_N = turn[N-1].cache_read + turn[N-1].cache_creation`, `drop = expected - actual`, `drop ≥ 5000 → invalidation`
- 6 events 모두 actual_cr = **17,164** 정확히 동일
- turn 2 (gap 0.2분), turn 30 (0.4분), turn 161 (11.1분), turn 164 (32.7분), turn 165 (1.0분), turn 187 (1.3분)
- 평균 drop 349k tokens, 총 2.1M / $7.86

---

## Round 1

### Steelman Advocate (Round 1)

**Core thesis:** v0.3.2의 prefix-continuity 기반 알고리즘은 Anthropic caching의 물리적 메커니즘을 직접 관측하는 방식이며, actual_cr = 17,164 invariant는 알고리즘이 노이즈가 아닌 실제 구조적 신호를 검출하고 있음을 독립적으로 입증한다.

**Supporting case:**

A. *알고리즘의 이론적 정합성* — "cache가 살아있으면 turn N의 cache_read ≈ turn N-1의 (cache_read + cache_creation)"은 Anthropic caching 작동 방식에서 직접 도출. v0.2가 정상 conversation extension을 누수로 분류한 반면 v0.3.2는 연속성 위반만 포착 → false positive 구조적 원인 제거.

B. *17,164 invariant가 감도 검증* — 6 events 모두 정확히 동일한 값은 우연 아님. invalidation 이후 "남아있는 최소 cache" = Claude Code의 안정적 기반 (시스템 프롬프트). (1) 알고리즘이 진짜 구조적 이벤트 잡음. (2) leaked 토큰 수 = 전체 - stable base로 물리적으로 정확.

C. *TTL 설명 가능성* — turn 161 (11.1분), turn 164 (32.7분)은 5분 TTL 초과로 설명. 나머지 4 events는 prefix 변경/breakpoint 재배치/내부 context 조작에서 발생한 invalidation.

D. *$7.86 산출의 정직성* — 2.1M tokens × ($3.75 - $0.30) / 1M ≈ $7.245, 표시값과 오차 범위 내. 기회비용 정의로 정직, 오히려 하한.

**Plausibility:**
- caching이 turn-to-turn prefix continuity 보장: 높음
- Claude Code가 stable context 유지: 17,164 invariant가 실증
- 5분 TTL 적용: turn 161/164 gap이 정확히 설명
- expected_cr 계산이 실제 토큰 수와 일치: API usage 필드 직접 읽음, 추정 아님
- 유일 plausibility 낮은 가정: Claude Code가 항상 last user message에 cache_control. 하지만 틀려도 알고리즘 무효화 안 됨.

**Reframe:** 진짜 가치는 "얼마를 낭비했는가"가 아니라 **"caching 구조 붕괴 turn을 transcript에서 역공학할 수 있음"**. 17,164 발견은 Anthropic 비공개 stable prefix size를 API usage만으로 추론한 포트폴리오 결과.

---

### Red Team (Round 1)

**Single biggest risk:** `expected_cr = prev_cr + prev_cc` 공식이 Anthropic API의 실제 계약이 아니다. 공개 문서에 이 누적 불변식 명시적 보장 없음. 만약 역엔지니어링 가설이라면 $7.86은 측정값이 아니라 잘못된 공식의 결과물.

**Failure Scenarios:**

**A. Auto-compaction misclassified as invalidation.** Claude Code는 context window 압박 시 자동 압축. compaction 이후 cache_read는 압축된 summary 토큰 수만. 트리거: context window 80%+ 도달. 6 events 모두 17,164에서 떨어지는 패턴은 compaction 후 공통 system prompt prefix만 남는 시나리오와 정확히 일치.

**B. Subagent fork이 독립 conversation thread를 생성.** subagent thread는 parent cache 상속 안 함. parent에 interleave되어 기록되면 도구가 sequential pair로 보고 drop 계산. 실제론 다른 thread의 첫 turn. 6 events 모두 thread boundary artifact 가능.

**C. 5,000 threshold가 Anthropic infrastructure noise 수준.** Anthropic 서버측 partial eviction, shard migration, 모델 배포로 cache_read 예측 불가 변화. 5,000-50,000 범위 drop이 사용자 행동과 무관한 이벤트.

**D. 17,164 invariant가 parser artifact.** 통계적으로 너무 깔끔. (1) 진짜 stable prefix이거나 (2) parser 버그 fallback. v0.2 false positive가 알고리즘 오류였다면, v0.3.2의 false positive는 파서 오류일 수 있음.

**Hidden assumptions:**
1. cache_creation/cache_read 같은 turn 내 누적 — 실제 비대칭 구조 (creation은 현재 turn, read는 다음 turn). 4 breakpoint partial hit 구분 불가.
2. turn sequence가 단일 사용자 session의 선형 대화 — tool calls, subagent events, MCP가 interleave.
3. 6 events가 독립 측정 — 같은 구조적 원인 6번 반복이면 1개 증거의 6중 카운트.

**Change-my-mind:**
- Anthropic API 문서/SDK에 공식 명시 → 공식 기반 인정
- 17,164가 실제 시스템 프롬프트 토큰 수와 일치 (직접 tokenize) → compaction 가설 무게
- 파서 raw API JSON round-trip 검증 → Scenario D 기각
- 짧은 세션(5 turns 이하)에서 동일 패턴 재현 → compaction 가설 배제

---

### Context Keeper (Round 1)

**핵심 컨텍스트:**
- 프로젝트 결함 패턴 (반복 5번): 추론 기반 semantic 가정 → 합성 fixture 통과 → 실데이터에서 깨짐. v0.3.2는 6번째 후보.
- v0.3.2 알고리즘 정확한 정의 + 임계값 5000 외부화
- 6 events 사실 정확: actual_cr=17,164 동일, 4 events TTL 미만, 2 events TTL 초과
- Anthropic 공식 문서 사실: 5분 TTL, 1h 옵션, max 4 breakpoint, creation $3.75/Mtok, read $0.30/Mtok

**불명확/누락:**
- Moderator 가정 #2 (Claude Code 항상 last user message에 cache_control): 공식 문서 없음, 내부 구현
- Moderator 가정 #3 (17,164 = system prompt + initial stable context): 데이터에서 관찰된 사실 = "동일하다"뿐, 의미는 추론
- TTL 미만 events 4개 (turn 2, 30, 165, 187): 왜 TTL 내에 drop했는지 설명 안 됨
- `expected_cr` 공식의 전제: partial cache hit, multi-breakpoint 독립 TTL 가능성 안 다룸
- Compaction 동작과 cache drop 관계: 정의되지 않음

**이미 결정된 사항:** v0.2 알고리즘 제거됨, tool_schema_bloat은 v0.4 deferred, threshold config 외부화, 109 tests green

---

## Round 2

### Steelman Advocate (Round 2 rebuttal)

**Scenario A (compaction): 가장 damaging 비판이고 부분 인정.** 17,164 floor는 진짜 ambiguous. compaction이 정확히 이 signature 생성 — 안정적 lower bound + 위에 layered. 데이터만으로 "17,164는 진짜 system prompt 크기" vs "post-compaction synthetic baseline" 구분 불가. **인정: Scenario A는 진짜 alternative explanation. invalidation-detection 로직을 materially 약화.**

**Scenario D (parser artifact): 완전 인정 안 하나, 기각 어려움.** 6 events가 정확히 17,164 동일은 의심스러움. 진짜 floor도 정확히 반복 가능. 구분 가능한 internal-consistency 체크: 다른 cache 변수들이 6 events 가로지르며 sensibly vary하는지 확인. parser bug는 fallback constant 고정하고 다른 필드 변동; 진짜 floor는 actual_cr 안정 + cache_creation 변동. **인정: cross-field consistency 체크 없이 Scenario D 기각 불가.**

**Reframed thesis:** 원래 thesis ("invalidation events 검출 가능") 살아있지만 **hypothesis-generating 도구**로만 신뢰 가능, reliable classifier 아님. 17,164 floor가 진짜 신호일 수 있지만 Scenario A+D 합치면 false-positive rate 미지수. 정직한 reframe: 알고리즘은 *원리적*으로 valid, (a) compaction event logging + (b) cross-field consistency 체크 추가되어야 invalidation count를 ground truth로 취급 가능. **프로젝트는 깨진 게 아니라 검증 레이어 1개 추가 필요.**

---

### Red Team (Round 2 focused)

**가장 강한 남은 attack: multiple cache_control breakpoints / 독립 TTL 문제.** Steelman이 안 다룸. Anthropic 4 breakpoint 동시 가능, 각 5분 TTL 독립. 공식 `expected_cr = prev_cr + prev_cc`는 prior turn의 *전체* prefix가 live라고 가정. breakpoint 1, 2 만료 + 3 warm이면 actual_cr은 partial sum, 공식이 예측 못 함. **partial hit를 매번 "누수"로 플래그**. cache가 설계대로 동작했는데. Steelman의 "17,164 invariant signal" 방어는 invariant *자체*에 valid, 하지만 multi-breakpoint partial hit 케이스를 구하지 못함 — partial hits도 consistent하지만 wrong한 expected 값 생성해서 signal처럼 보임.

**$7.86 "leak" 라벨에 대해:** Steelman 옳음 — math는 opportunity cost로 structurally honest. 계산 자체 fabricated 아님. 하지만 **leak로 보고하는 것은 사용자가 잘못한 게 있거나 회수 가능을 함의**. TTL expiry, compaction boundary, multi-breakpoint partial hit는 사용자 통제 밖 API 메커니즘. "leak"가 아니라 "unrecoverable cache miss cost" / "cache turnover cost"가 honest. 숫자 정확성과 무관한 framing bug.

**Portfolio? No** — multi-breakpoint partial-hit 케이스가 valid API 동작에 systematic false-positive leak flag 생성. uncontrollable cost를 "leak"로 mislabel은 Hashed/A41 reviewer에 domain knowledge gap signal로 읽힘.

---

### Context Keeper (Round 2 verification)

**Q1: actual_cr = 17,164가 parser artifact인가?**

**Finding: NO. parser fallback일 수 없음.**

`tlp/parser/claude_code.py` lines 222-230, `_parse_usage`:
```python
return Usage(
    cache_read_tokens=int(u.get("cache_read_input_tokens", 0) or 0),
    ...
)
```
유일한 fallback = 0. 17164 생성 코드 경로 없음. raw JSONL에 직접 존재 (line 36 verbatim).

**Q2: compaction 증거가 있는가?**

**Finding: compaction-type event NO. 대신 일관된 structural marker 발견.**

전체 event type inventory (1538 lines):
- `assistant` (656), `user` (414), `last-prompt` (87), `mode` (87), `permission-mode` (87), `ai-title` (86), `file-history-snapshot` (48), `attachment` (36), `system` (35), `queue-operation` (2)
- `summary`, `compaction`, `context_window_full` 종류 **0회**.

**6 reset events 모두 직전에 `last-prompt` event 있음:**

| Reset line | Timestamp | 직전 event | 거리 |
|---|---|---|---|
| L36 | 08:45:18 | `last-prompt` at L31 | 5 lines |
| L250 | 09:19:05 | `last-prompt` at L246 | 4 lines |
| L1072 | 12:26:34 | `last-prompt` at L1067 | 5 lines |
| L1097 | 13:02:07 | `last-prompt` at L1087 + `queue-operation` at L1096 | ~10 lines |
| L1102 | 13:03:08 | 같은 sub-session 연속 | — |
| L1289 | 13:40:38 | `last-prompt` at L1284 | 5 lines |

`last-prompt` event는 사용자의 새 typed message 포함 (L31 한국어 project brief, L246 "1", 등). 같은 session 내 새 conversation turn 표시. **compaction 아님.** 53초 gap이 idle-triggered compaction 발생하기 너무 짧음.

**Q3: 첫 assistant turn의 cache_creation이 17,164 의미 보여주는가?**

**Finding: 17,164는 거의 확실히 stable system-prompt prefix.**

L20 첫 assistant turn (ts=08:44:40):
- `cache_read_input_tokens` = 17,071 (이전 세션에서 carry-over)
- `cache_creation_input_tokens` = 15,729
- 합 = 32,800

L25 두번째 assistant turn (ts=08:45:06):
- `cache_read_input_tokens` = 32,800 (정확히 prior read + creation 일치)

L36 (last-prompt boundary 직후):
- `cache_read_input_tokens` = 17,164
- `cache_creation_input_tokens` = 25,311

L36의 17,164 ≈ 17,071 (이전 세션 stable prefix) + 93 (tool def 작은 변경). **L20-L30의 대화 history 전부 drop. system prompt / tool definitions만 cache.**

이 패턴이 6 resets 가로질러 동일하게 반복: `cache_read`가 정확히 17,164로 snap back, `cache_create` 큰 값 (25K → 122K → 463K → 475K → 477K → 554K) — **전체 대화 history가 처음부터 cache로 다시 쓰여짐**.

**17,164 = system-prompt-only cache prefix.**

---

## Synthesis (Moderator)

**결정적 발견:** 6 events는 invalidation 아니라 **Claude Code 디폴트 동작** — 매 새 user turn (`last-prompt`)마다 cache_control breakpoint를 system prompt 끝에 두고 conversation history 전체 재캐싱.

**$7.86은:**
- 측정값으로 정확 (실제 청구된 cache_creation 단가)
- 분류 라벨로 misleading ("leak"는 사용자 행동 변경으로 회수 가능 함의)
- 사용자가 prompt 수정으로 못 줄임 — Claude Code architecture 비용

**Portfolio 판정:** Red Team과 일치 — ship 안 함. domain knowledge gap signal.

**6번째 같은 카테고리 결함:** v0.3.2는 v0.2와 다른 방식으로 같은 실수 — *"이 메트릭이 0이 아닌 정상 케이스를 검증했나"가 아니라, "이 메트릭이 진짜라도 사용자가 줄일 수 있는 종류의 비용인가"를 검증 안 함*.

## Recommended actions

1. lever rename: `cache_miss_penalty` → `cache_turnover_cost`
2. 분리 표시: TTL 초과 turnover (회피 가능, 빠르게 응답) vs Claude Code architecture turnover (회피 불가능, system-level)
3. `stable_prefix_tokens` 같은 reverse-engineering 결과를 별도 출력 (포트폴리오 가치)
4. v0.4 spec-checklist 추가 룰: **"새 메트릭이 X > 0인 정상 워크플로 + 사용자가 그것을 줄일 수 있는 mechanism도 spec에 명시해야 함."**
