# Architectural Decision Records

이 디렉터리(`docs/adr/`)는 프로젝트의 **canonical decision record**다.

운영 정책 변경이 어떤 결정에 근거하는지 추적할 수 있도록 유지한다.

---

## ADR Status 정책

| Status | 의미 |
|---|---|
| `Proposed` | 검토 중. 아직 확정되지 않음 |
| `Accepted` | 채택됨. 현재 플랫폼 운영 기준 |
| `Superseded by ADR-XXXX` | 다른 ADR로 일부 대체됨. 전부 대체되면 파일을 삭제하고 원문은 git history로 본다 |
| `Deprecated` | 더 이상 권장하지 않지만 제거하지 않음 |
| `Rejected` | 검토 후 채택하지 않기로 결정 |

---

## ADR Template

```markdown
# ADR-XXXX: 제목

## Status

[Proposed | Accepted | Superseded by ADR-XXXX | Deprecated | Rejected]

## Context

결정이 필요했던 배경과 제약 조건을 기술한다.

## Decision

무엇을 결정했는지 명확하게 기술한다.

## Consequences

| Positive | Negative |
|---|---|
| 긍정적 결과 | 부정적 결과 또는 트레이드오프 |

## Operational impact

운영 절차, 설정, 도구에 미치는 영향을 기술한다.

## Migration notes

기존 시스템/코드에서 이 결정으로 전환할 때 필요한 작업을 기술한다.

## Related

- 연관 ADR, 문서, 정책
```

---

## ADR 인덱스

이 디렉터리의 번호가 매겨진 Markdown 파일이 ADR 목록이자 canonical record다. 새 ADR을 추가하거나 Status를 바꾸면 해당 ADR 파일을 갱신한다.
