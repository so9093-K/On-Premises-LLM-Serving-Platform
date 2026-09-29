# ADR-0042: 저장소 안의 검증 근거 시스템을 제거하고 qualification은 선언으로 둔다

## Status

Accepted

- Supersedes: ADR-0032, ADR-0033, ADR-0036 (파일은 삭제했다. 원문은 git history에 있다)
- Partially supersedes: [ADR-0030](./0030-target-architecture-state-and-artifact-boundary.md) 6절,
  [ADR-0034](./0034-main-model-host-resource-variant.md) 4절,
  [ADR-0035](./0035-capability-based-hardware-admission-and-transparent-operations.md)의 durable evidence 부분

## Context

ADR-0032·0033·0036은 Main Model의 `qualification.status=verified`를 machine-readable 근거와 묶었다.

- `configs/qualification_evidence.yaml`(근거 catalog)과 `configs/qualification_checks.yaml`(check 목록)
- `evidence/qualification/runs/*.json` receipt
- runtime-validation report에서 candidate를 만들고 plan digest로 승격하는 도구
  (`make qualification-candidate`, `qualification-promote`, `qualification-status-promote`)
- `make validate`에서 현재 verified profile마다 일치하는 근거가 있는지 보는 governance 검사

실제로 쓰인 모습은 달랐다. 레코드 다섯 개 중 네 개는 profile 주석을 옮겨 적은 `legacy_backfill`이었고,
승격 도구로 만든 `qualified_run`은 하나였다. 이 체계를 유지하는 코드와 테스트는 약 3,300줄이었다.
governance 검사가 확인하는 것은 "catalog에 같은 model/revision을 적은 레코드가 있는가"였고, 그 레코드도
결국 사람이 적거나 사람이 승격한다. 검증 자체를 강제하지 못하면서 profile을 바꿀 때마다 근거 파일,
check 목록, receipt를 함께 맞춰야 했다.

## Decision

1. 근거 catalog, check 목록, receipt, candidate/승격 도구, governance 검사를 제거한다.
2. `qualification.status`(`verified` / `unverified`)와 Deployment Target의 `qualification_status`는
   **maintainer 선언**으로 남긴다. 공개·Admin API와 Console 표시, `confirm_unverified` 확인 절차는
   바뀌지 않는다.
3. profile을 추가하거나 model ID·revision·`deployed_input`을 바꾸면 `unverified`로 두고, 실제 장비에서
   전환과 `make runtime-validate`가 통과한 뒤 `verified`로 바꾼다. 어떤 장비에서 무엇을 확인했는지는
   profile 주석과 commit/PR 설명에 남긴다. 선언이 실제 검증을 넘어서지 않는지는 review가 책임진다.
4. runtime-validation report에서 qualification 전용 필드(`qualification_check_id`,
   `qualification_context`)를 뺀다. report는 check 결과와 지연만 기록한다.

## Consequences

| Positive | Negative |
|---|---|
| profile 변경이 profile 파일 하나의 변경으로 끝난다 | `verified`가 근거 파일과 기계적으로 연결되지 않는다 |
| 약 3,300줄의 도구·검증·테스트와 전용 문서가 사라진다 | 과거 검증의 장비·driver 기록은 주석과 git history에서 찾아야 한다 |
| Console은 "검증 근거" 대신 "검증 상태"라는 실제 의미를 보여 준다 | |

## Operational impact

- `make qualification-*` 명령과 `reports/qualification/`이 없어진다.
- `make validate`의 contracts 단계에서 qualification evidence 검사가 빠진다.
- 모델 전환 API와 `confirm_unverified` 동작은 그대로다.

## Related

- [6. 모델 운영](../06_model_operations.md) — Qualification 선언
- [13. 변경 가이드](../13_change_guide.md) — Qualification 선언을 되돌리는 변화
