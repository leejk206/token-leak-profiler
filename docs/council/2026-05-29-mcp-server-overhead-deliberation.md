# Council Deliberation — mcp_server_overhead v0.6.0

- Date: 2026-05-29
- Rounds: 2 (Steelman, Red Team, Context Keeper)
- Verdict: 알고리즘 옳음, "confirmed" 라벨 룰 5 위반 → v0.6.1 fix

## 핵심 발견

1. 사용자 핵심 의심 (pal MCP indirect use) — 데이터로 반증 (Context Keeper)
2. 진짜 문제 — confirmed 라벨이 추정 결과에 붙음 (룰 5 위반)
3. v0.6.1 fix: evidence_kind 정교화
4. v0.7 backlog: partial use granularity
5. README 블로그 정렬 주장 scope 명시화 필요

## Actions

1. evidence_kind="confirmed" → "estimated" (새 enum 추가 또는 메타데이터화)
2. README "6/6 (per-session retrospective)" 명시
3. v0.7 backlog: partial use, tool schema 실측
