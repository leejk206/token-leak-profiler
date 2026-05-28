# 토큰 누수 측정기 만들기 — 도그푸딩이 spec을 두 번 뒤집은 이야기

> 2026-05-28 · LLM 비용의 어느 부분이 실제 작업과 무관하게 새는지를 6개 lever로 분류하는 CLI를 만들었다. spec → plan → subagent execution으로 하루 만에 v1을 찍었고, 만든 도구를 자기 자신 세션에 돌려본 순간 두 개의 구조적 버그가 드러났다. 이 글은 그 사이클 — 설계 의도, 구현 흐름, 도그푸딩에서 나온 발견 — 의 기록이다.

## 문제

LLM 에이전트를 쓰면 토큰 비용이 빠르게 누적된다. 직관적으로 "프롬프트 길어서 그런가 보다" 정도로 넘어가기 쉬운데, 실제 청구서를 뜯어보면 *일은 안 했는데 컨텍스트에 실려서 매 턴 과금되는 토큰* 비중이 의외로 크다. 총 토큰 수만 보면 그 안에서 **어떤 종류**가 낭비인지 모른다.

이걸 6개 카테고리(lever)로 분해해서 "여기서 X% 줄일 수 있다"를 숫자로 보여주는 도구가 필요했다. 측정 + actionable suggestion 까지.

## 6 lever

| Lever | 무엇 | 처방 |
|---|---|---|
| **stale_context** | 초반에 실려서 후속 턴에 안 쓰이는데 매 턴 재과금되는 메시지 | 압축 / 삭제 |
| **redundant_restatement** | 시스템 프롬프트·이전 답변이 거의 동일하게 반복 | 시스템 프롬프트로 이동 |
| **tool_schema_bloat** | 매 호출마다 실리는데 실제로 안 불리는 툴 정의 | 호출 안 되는 정의 제거 |
| **verbose_tool_results** | 툴이 뱉은 결과 중 모델이 실제로 인용·사용한 비율 낮음 | truncate / summarize |
| **reasoning_overrun** | 답에 안 반영된 사고 토큰, 같은 결론 반복 | `max_thinking_tokens` 하향 |
| **format_boilerplate** | 매 응답의 정형 머리말·맺음말·장식 | "no preamble" 지시 / stop sequence |

각 lever는 독립 분석기(analyzer)로 구현. 새 lever는 `analyzers/<name>.py` 파일 하나 추가로 끝나는 plugin-like 구조.

## 어떻게 만들었나

Claude Code의 `superpowers` 스킬셋을 따라갔다. 한 단계도 건너뛰지 않고:

1. **brainstorming** — 6개 핵심 의사결정을 multiple-choice로 좁힘. 입력 형식 (Claude Code 세션 로그), 스택 (Python), 분석 단위 (단일 세션), 출력 (rich CLI + JSON), 가치 제안 (측정 + 처방), 분석기 범위 (6개 모두 v1).
2. **spec** — 14절짜리 design doc. 데이터 모델, 분석기별 알고리즘, CLI surface, 에러 처리, 테스트 전략까지. self-review에서 두 군데 inline 수정.
3. **writing-plans** — 18개 task로 분해된 TDD 플랜. 각 task는 failing test → 구현 → passing → commit 5스텝.
4. **subagent-driven execution** — task당 fresh subagent 1개로 implementer dispatch, 끝나면 두 단계 review(spec compliance → code quality), 이슈 있으면 fix-up subagent. 18 tasks를 main context 오염 없이 처리.

24 commit으로 끝났고 49 tests 통과. 첫 smoke test는 실제 Claude Code transcript 352-turn 세션에 대해 traceback 없이 동작.

```bash
$ tlp analyze ~/.claude/projects/<slug>/<session>.jsonl
────── Token Leak Profile — session ... ───────
turns: 88  ·  input(fresh): 100  ·  output: 82,186  ·  cost: $3.21
cache_read: 3,591,449  ·  cache_creation: 239,344
                      Leak by lever
  lever                   tokens   cost ($)   % of total
  reasoning_overrun       22,352     0.3353        27.2%
  verbose_tool_results    10,101     0.0303        12.3%
  ...
Effective leak (cache-adjusted): ~$0.34 (blended input rate $0.52/Mtok)
```

여기까지가 "spec → 작동하는 v1"의 평탄한 줄거리다. 진짜 학습은 그다음에 일어났다.

## 도그푸딩 1 — Cache 보정과 redacted thinking

만든 도구를 *이 도구를 만들고 있던 그 세션 자체*에 돌렸다.

```
input: 449 tok        ← 이상함
output: 651,560 tok
cost: $25.06
```

input이 449 토큰밖에 안 되는데 비용이 $25? Anthropic의 prompt caching 때문이다. 동일 컨텍스트가 반복되면 `cache_read_input_tokens`로 들어가서 단가가 1/10($3 → $0.30/Mtok). 첫 표시는 fresh input만 보여줘서 컨텍스트 부하를 과소 표시.

**Fix 1**: 헤더에 `cache_read` / `cache_creation` 표시. JSON에 `effective_cost_usd` 필드 — blended input rate로 누수 비용을 다시 계산.

```python
# blended rate = weighted avg of input + cache_read + cache_creation by token share
total_input_like = total_input + total_cache_read + total_cache_creation
blended_rate = (
    pricing.input_per_mtok * total_input
    + pricing.cache_read_per_mtok * total_cache_read
    + pricing.cache_creation_per_mtok * total_cache_creation
) / total_input_like
```

그리고 `reasoning_overrun`이 0으로 나옴. grep해보니 transcript에 thinking block은 50개 있었다. 그런데 다 `{"type":"thinking", "thinking":"", "signature":"<encrypted>"}` — **redacted thinking**. Anthropic이 extended thinking 콘텐츠를 클라이언트에 노출 안 하고 암호화된 signature만 준다. 토큰은 `usage.output_tokens`에 포함돼서 청구되지만 우리 파서는 `thinking:""` → tokens=0 → 분석기가 skip.

**Fix 2**: thinking block은 존재하지만 콘텐츠가 비어있는 경우 `output_tokens - text_tokens - tool_use_tokens`로 thinking tokens를 역산. Anthropic의 usage 자체는 실측치라서 confidence는 `"mid"`.

이 두 fix를 적용하니 reasoning_overrun이 0 → 147,850 tok ($2.22)로 점등. 전체 세션 비용 중 7.8% 누수. v1에선 본인 도구가 본인 가장 큰 누수를 못 봤다.

## 도그푸딩 2 — 토큰을 1.6× 부풀린 더 큰 버그

다른 세션(leejk personal site 작업)에 돌려봤다.

| Session | turns | cost | leak% | reasoning_overrun |
|---|---|---|---|---|
| d1fa51cc | 88 | $3.21 | 10.6% | 22k tok |
| 3fb14e10 | 203 | $7.91 | 10.7% | 56k tok |
| **5c7286b1** | 141 | $10.67 | **19.2%** | **136k tok** |

5c7286b1만 누수율이 두 배. "이 세션에서 뭔가 비효율적인 일이 있었나?" 싶어서 들여다봤더니, 26개 thinking 턴 **전부** `text=0, tool_use=0`. 사고는 했는데 그 다음 어떤 출력도 없었다는 뜻. 그게 가능한가?

raw JSONL을 까봤더니:

```
line 19: type=assistant content=[thinking]  usage.output=268
line 20: type=assistant content=[tool_use]  usage.output=268
```

같은 `message.id`. 같은 `usage.output_tokens`. Claude Code가 한 assistant 응답의 각 content block을 별도 JSONL event로 로깅하면서, 각 event에 똑같은 usage를 그대로 복제해서 적었다.

그러니까:
- 한 번의 API call (268 토큰 청구)
- 두 개의 JSONL event (각각 usage.output=268 표시)
- 우리 파서: 두 개의 Turn 생성, 두 번 합산 → 청구의 2배로 카운트
- 게다가 thinking 단독 event는 "사고는 했는데 output 없음" → leak으로 분류

이게 누적되면 **세션 비용 자체가 1.6×에서 2× 부풀려진다**. 5c7286b1이 outlier로 보였던 건 진짜 outlier여서가 아니라, 그 세션이 streaming-split 패턴이 더 많았기 때문.

**Fix 3**: 파서를 `message.id`로 묶기. 연속된 assistant event가 같은 `message.id`면 block들을 concat하고 usage는 한 번만 (defensive하게 max output_tokens 선택). 한 번에 50줄 정도 변경.

```python
# Second pass: build turns, grouping consecutive assistant events with the
# same message.id into a single Turn.
while i < len(events):
    if ev_type == "assistant":
        message_id = msg.get("id")
        grouped_content = list(msg.get("content", []) or [])
        grouped_usage = msg.get("usage")
        j = i + 1
        while j < len(events):
            nxt = events[j]
            if nxt is assistant and same_message_id:
                grouped_content.extend(nxt.content)
                grouped_usage = max_by_output(grouped_usage, nxt.usage)
                j += 1
            else:
                break
        turns.append(Turn(blocks=grouped_content, usage=grouped_usage))
        i = j
```

**Fix 4** (Fix 3와 짝): `reasoning_overrun`의 ratio denominator에 `tool_use_tokens` 포함. Edit/Write/Bash 같은 tool 호출도 productive output이다. text=0이라고 해서 thinking을 다 leak으로 분류하면 안 된다.

## 수정 전후

| Session | 수정 전 turns/cost/leak% | 수정 후 turns/cost/leak% |
|---|---|---|
| d1fa51cc | 88 / $3.21 / 10.6% | 64 / $1.65 / 10.2% |
| 3fb14e10 | 203 / $7.91 / 10.7% | 162 / $4.71 / 6.9% |
| 5c7286b1 | 141 / $10.67 / 19.2% | 111 / $5.65 / **25.0%** |
| 현재 (tlp dev) | 433 / $28.43 / 7.8% | 382 / $19.98 / 4.6% |

비용이 정확히 줄어들었다 (1.6-2.0×). 누수율은 일부 올라가고 일부 내려갔는데, 분자(누수)와 분모(비용)가 둘 다 변해서 그렇다. 절대 누수 토큰은 모두 감소.

흥미로운 점: 수정 후에도 **5c7286b1은 25% 누수율로 진짜 outlier**. 더 이상 파서 아티팩트로 설명 안 됨. 그 세션에서 실제로 thinking 94k 토큰이 과잉이었다. 즉, 도구의 진짜 시그널이 노이즈 위로 솟아오름.

## 교훈 — spec과 plan 단계에서 못 잡았던 것

이 두 버그는 spec → plan → TDD subagent execution 사이클에서 한 번도 나오지 않았다. 49개 unit/integration test 통과하고, 합성 fixture 6개 다 정상 분류했다. 그런데 실데이터에서 뒤집힘.

이유:

1. **합성 fixture는 streaming-split을 흉내 내지 않았다.** 한 어시스턴트 응답을 한 줄에 다 넣었기 때문에 message.id 그룹핑 필요성을 시뮬레이션할 일 자체가 없었음. spec의 `§14 Open Questions`에 "Claude Code transcript의 정확한 thinking block 표현 — 첫 파서 작성 시 실제 sample 확인 후 fix"라고 적어놨는데, T18(real-transcript sanity)에서 turn count랑 traceback 없음만 보고 통과시켰다. **이벤트 구조 분포를 봤어야 함.**

2. **redacted thinking을 v1 spec에서 아예 가정하지 않았다.** Anthropic의 extended thinking 명세를 안다고 생각했는데, 실제로 Claude Code transcript에 어떻게 직렬화되는지는 확인 안 했음. spec 설계 시 가정이 깔린 부분은 항상 한 번은 실데이터로 깨야 한다.

3. **cache는 처음부터 v2로 미뤘는데, dogfooding 한 번에 v1으로 옮겨야 함이 명백해짐.** spec §13에 "v2: cache 보정"이라고 적은 게 사실은 v1 critical path였다. Anthropic 워크플로에서 cache는 옵션이 아니라 기본.

`spec → 구현 → 진짜 사용` 사이클이 짧을수록 spec의 빈틈이 빨리 드러난다. 합성 테스트가 진짜 사용을 대체할 수 있다고 믿으면 안 된다.

## 도구의 현재 상태

- 4 commit 추가 (총 28)
- 53 tests green, ruff clean
- 자기 자신의 가장 큰 누수(reasoning_overrun)를 정확히 탐지하고, blended cache rate로 effective cost 환산. 더 이상 자기 비용을 부풀리지 않음.
- v2 backlog: `tlp aggregate <dir>` 다중 세션 비교, Markdown/HTML 리포트, suggestion 적용 시 절감량 시뮬레이션.

## 좌표

- 코드: 로컬 (정리 후 깃허브 push 예정)
- spec: `docs/superpowers/specs/2026-05-28-token-leak-profiler-design.md`
- plan: `docs/superpowers/plans/2026-05-28-token-leak-profiler.md`

## 마무리

도구를 만들 때 가장 중요한 건 spec이라고 생각해 왔는데, 이번엔 spec이 "충분히 자세하다"는 신뢰가 오히려 함정이었다. 18 tasks × 4-5 step씩 빈틈없이 TDD해도 가정이 틀렸으면 다 무너진다. 도그푸딩 30분이 spec writing 2시간보다 더 많은 결함을 찾았다.

다음 v2부터는 spec 안에 "실데이터 검증 게이트"를 명시적 task로 넣을 계획. fixture 한 개가 아니라 실제 세션 3개 + 각 세션의 event-type 분포 dump까지 PR 머지 전 의무 절차로.
