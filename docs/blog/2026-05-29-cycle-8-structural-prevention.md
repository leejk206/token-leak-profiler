# 도그푸딩 8사이클 — 결함이 일어나기 전에 막은 첫 사이클

> 2026-05-29 · v0.7.0. 이전 글([도그푸딩 7사이클](2026-05-29-dogfooding-seven-cycles.md))이 "8번째가 안 나오면 메커니즘 작동 증거"로 끝났다. v0.7은 그 8번째를 결함 *발생 전*에 막은 첫 사이클이다.

## 7사이클 글의 미해결 약속

> "같은 카테고리 결함이 8번째 안 나오면 *그건 메커니즘이 작동한 증거*. 나오면 *룰 7이 추가될 것*. 어느 쪽이든 도구는 한 발 더 정직해진다."

7사이클 끝에 6개의 spec-checklist 룰이 있었다. 근데 룰은 *내가 다음 분석기 spec을 쓸 때 참조*하는 문서였을 뿐. 룰을 *적용 안 함*이 결함 발생의 원인이었음을 7사이클이 보여줬다 (룰 5를 v0.4에서 만들고 v0.6에서 위반).

v0.7의 질문: *어떻게 룰을 적용 안 할 수 없게 만드나*.

## 구조적 차단

v0.7은 spec-checklist 룰을 **코드 자체에 심었다**.

### Step 1: ClassVar 강제

`BaseAnalyzer`에 두 메타데이터 의무화:

```python
class BaseAnalyzer:
    prescription: ClassVar[str | None]
    measurement_basis: ClassVar[Literal["measured", "estimated", "heuristic"]]

    def __init_subclass__(cls, **kw):
        for attr in (..., "prescription", "measurement_basis"):
            if not hasattr(cls, attr):
                raise TypeError(f"{cls.__name__} missing required class attribute: {attr}")
```

새 분석기를 만들 때 두 필드를 *선언 안 하면 import 자체가 실패*. 메타데이터를 "잊는" 경로가 차단됨.

### Step 2: 룰 5/6 자기-적용 테스트

`tests/test_rules_self_application.py`:

```python
@pytest.mark.parametrize("cls", registry.all(), ids=[c.name for c in registry.all()])
def test_rule_5_prescription_present_when_measured(cls):
    """Rule 5: measured analyzers must declare non-empty prescription."""
    if cls.measurement_basis == "measured":
        assert cls.prescription is not None and cls.prescription.strip(), \
            f"{cls.__name__} measured but lacks prescription — rule 5 violation"
```

11개 분석기 × 2개 테스트 = 22 케이스 자동 검증. 새 분석기를 추가할 때 메타데이터가 일관되지 않으면 CI 실패.

### Step 3: 자기-적용 부작용

테스트를 처음 돌렸을 때 *기존* 6개 분석기가 룰 5 위반으로 떨어졌다:

| 분석기 | 원래 라벨 | 실제 출력 | 변경 |
|---|---|---|---|
| stale_context | measured | signal만 emit | → heuristic |
| verbose_tool_results | measured | signal만 emit | → heuristic |
| reasoning_overrun | measured | signal만 emit | → heuristic |
| system_prompt_audit | measured | signal만 emit | → heuristic |
| roundtrip_inflation | measured | signal만 emit | → heuristic |
| tool_result_repetition | measured | signal만 emit | → heuristic |

"토큰 수치는 측정하지만 낭비 판정은 사용자 검토 없이 못 한다" — 이게 `heuristic`의 정의. 6개 분석기가 자기 라벨을 잘못 쓰고 있었다. 룰 6의 자기-적용이 *기존 코드의 라벨 정직성*까지 강제.

## 결함 *전*에 막은 의미

7사이클 모두 *결함을 발견하고 코드를 고친 후* 룰을 추가했다.

| 사이클 | 결함 발생 | 룰 추가 |
|---|---|---|
| 1-7 | 실제 결함 → 디버깅 → 코드 fix | 그 다음에 룰 추가 (재발 방지용 메모) |
| 8 (v0.7) | 결함 발생 *안 함* | 메커니즘 추가 → 미래 결함을 *구조적으로* 차단 |

이게 "메커니즘 작동 증거"의 의미. 도그푸딩 패턴 자체가 변했다 — *retrospective 룰 축적*에서 *proactive 메커니즘 심기*로.

## 부가 작업

### measurements.yaml 승급 경로

v0.6.1에서 `mcp_server_overhead`가 `200 tok/tool × count`를 confirmed로 표시했던 게 7번째 결함이었다. v0.7은 *측정 기반으로 confirmed가 가능한 경로*를 추가:

```yaml
# tlp/config/measurements.yaml
tools:
  mcp__pal__chat: 412
  mcp__playwright__browser_click: 187
```

unused MCP 서버의 모든 tool이 측정값을 갖고 있으면 → `estimated` → `confirmed` 자동 승급. 부분 커버리지면 `mixed` 라벨로 정직하게 표시. measurements 없으면 기존 `heuristic` 기본값 유지.

### MCP partial-use 분기

v0.6은 *서버 단위 0회 호출*만 잡았다. Council Round 2에서 Red Team이 지적한 Scenario B (서버에 도구 80개 활성화, 1개만 사용 — 79개 overhead invisible)를 v0.7이 닫음:

```python
elif used_count / total_count < min_use_ratio:   # default 0.3
    # unused 부분집합을 별도 Finding으로 emit
    location = f"mcp_server[{server}].partial({unused_count}/{total_count})"
```

## v0.7 도그푸딩 결과

```
$ tlp analyze <current-session> --min-confidence low

Confirmed leak:    $7.34   ← measured + actionable
Estimated leak:    $0.03   ← heuristic + actionable (MCP unused)
Attention signals: $10.11  ← measurement without verified prescription
```

7사이클 ($3.62 / $0.03 / $10.07)과 거의 같은 비율. partial-use Finding은 *없음* — 현재 세션에는 0회 호출 서버만 있어서 서버-단위 branch가 먼저 잡음. v0.7 분기는 정상 동작하지만 트리거 조건이 이 세션엔 없음.

**새 결함은 발견 안 됨.** 8번째 동일 카테고리 결함 후보가 0이다. 그러면 메커니즘이 작동한 증거인가? 답: *현재 한 세션에서는*. 다른 사용자가 도구를 쓰기 전까진 확정 못 한다.

## 메타-룰 축적의 종착점

룰 6개 → 룰을 *코드 contract*로 변환 → 룰을 *테스트*로 변환. 같은 카테고리 결함의 8번째가 발생하려면 다음 셋 중 하나가 깨져야 함:

1. 누군가 `__init_subclass__` 검증을 우회 (불가능, Python class 생성 단계)
2. 누군가 `test_rules_self_application.py`를 삭제 (PR review에 잡힘)
3. *룰 7이 필요한 새 카테고리*의 결함 발생

3번이 진짜 다음 도그푸딩 사이클의 조건. 1번/2번은 의도적 사보타주 아니면 안 일어남.

## 8사이클 핵심

7사이클 글이 "결함 발견 → 룰 축적 → 메커니즘"의 점진적 패턴을 보여줬다. 8사이클은 그 메커니즘이 *작동 가능한 상태로 코드에 박힌* 순간이다.

룰을 6번 쓰면서 깨달은 것: *내가 룰을 쓴 다음 그 룰을 적용 안 한다*. 사람이 룰을 보는 빈도와 룰이 적용돼야 하는 빈도가 안 맞음. 해결은 룰을 *내가 안 봐도 자동 적용되는 자리*로 옮기는 것이었다.

## v0.8 백로그

- **pre-commit hook**: rule self-application test를 commit 단계로. CI 아닌 *local commit 단계*에서 차단
- **Anthropic count_tokens API 통합**: `tlp count-tokens --tools tools.json` 명령으로 measurements.yaml 자동 populate. estimated → confirmed 승급 후보 늘림
- **외부 사용자 onboarding**: PyPI 패키지화. 도구가 *나 외의 사용자*를 처음 만남

8사이클은 *내가 만든 도구가 내 미래 실수를 막는 첫 단계*였다. 9사이클 이후는 *내가 안 만든 사용 패턴*이 도구를 바꿀 차례다.

코드: [github.com/leejk206/token-leak-profiler](https://github.com/leejk206/token-leak-profiler) · 174 tests · v0.7.0
