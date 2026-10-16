# ADR-0037: 배포 권한을 로컬 생명주기로 통일하고 원격 Release 상태 머신을 제거한다

- Status: Accepted; 운영자 명령의 진입점은 [ADR-0039](./0039-operator-intent-lifecycle-and-diagnostics.md)에서 구체화; 소스 패키지 결정은 [ADR-0046](./0046-source-transport-is-not-platform-authority.md)으로 대체
- Date: 2026-09-20
- Refines: [ADR-0013](./0013-env-lifecycle-non-destructive-sync.md), ADR-0023, [ADR-0030](./0030-target-architecture-state-and-artifact-boundary.md)

## Context

저장소에는 `scripts/deploy/deploy_compose_release.sh`와
`scripts/deploy/apply_remote_release.sh` 중심의 **두 번째 배포 권한**이 존재했다.

이 경로는 원격 소스 전달, `rolling/full` 모드 선택, 불변 Release 디렉터리,
`current/runtime-current` 심볼릭 링크 전환, 대상 `.env` 수정, Runtime 이미지 승격,
변경 서비스 계산, Ready 확인과 자동 Release Rollback을 소유했다.

당시 플랫폼은 배포 대상별 로컬 생명주기로 이미 수렴하고 있었다.
이후 ADR-0039는 동일 권한의 운영자 명령 진입점을
`make up/status/down/logs/reset/purge`로 정리했다. 관련 권한은 다음과 같이 분리된다.

- 보조 Runtime 변경: Runtime Controller
- Main Model 전환·Rollback: Main Model Control
- 설정 변경: Configuration Plan/Apply/Verify 계약
- 결정론적 Release 패키징: 배포와 별개의 Artifact 관심사였음
- Qualification 근거: 별도의 검증 관심사였음

별도 원격 Release 상태 머신을 계속 유지하면 새로운 Runtime 정책을 현재
호스트·Control Plane 생명주기와 원격 배포 수렴·Rollback 양쪽에 구현해야 한다.
그 결과 권한이 중복되고 Runtime 동작이 소스 전달 방식에 종속된다.

## Decision

### 1. Canonical 배포 생명주기는 대상별 로컬 생명주기다

저장소가 소유하는 배포 대상은 해당 호스트의 Checkout/Workspace에서 상태를 적용한다.
ADR-0039에 따라 운영자는 `make up`을 진입점으로 사용하며,
빌드·모델 준비는 별도의 운영자 명령이 아니라 내부 수렴 단계다.

`make up`은 선택한 대상의 Artifact 수렴, 전체 Stack 구성 및 Ready 확인을 소유한다.
기동 이후의 Runtime·Main Model 변경은 별도의 Release Executor가 아니라
각 Control Plane API가 소유한다.

외부 자동화가 SSH 등을 사용해 같은 명령을 원격에서 호출하는 것은 가능하지만,
저장소는 독립적인 원격 배포 프로토콜이나 상태 머신을 소유하지 않는다.

### 2. 원격 Release 전달과 Rollback 권한을 제거한다

다음 항목은 더 이상 유효한 배포 계약이 아니다.

- 저장소가 소유하는 원격 소스 전달
- `rolling` / `full` 배포 모드
- `DEPLOY_PATH/releases/<id>`
- `current` / `runtime-current` Release 심볼릭 링크 전환
- 배포 시점 이미지 승격 입력
- 이전 Release Tree와 비교한 변경 서비스 계산
- 원격 Release용 `.env` 백업·복구 절차
- Release 디렉터리 기반 Rollback 상태 머신
- 저장소가 소유하는 SSH 배포 정책

컴포넌트별 Rollback은 실제 소유자가 계속 담당한다.

- Main Model Control: 전환 실패 시 Last-known-good 상태 복원
- Runtime Control: 검토된 Runtime Transition Plan 적용
- Configuration: 검토된 변경 Plan·History 계약에 따른 수정
- Host/Source 복구: 운영자 또는 Source Control이 변경을 되돌린 뒤
  동일한 로컬 생명주기와 검증을 다시 수행

### 3. 배포와 독립적인 결정론적 Release Artifact — 후속 ADR에서 대체됨

> **이전 결정 기록:** 이 절의 소스 ZIP/Release Manifest 유지 결정은
> [ADR-0046](./0046-source-transport-is-not-platform-authority.md)에 의해 대체됐다.
> 현재 저장소는 소스 ZIP 또는 Release Manifest 계약을 소유하지 않는다.

당시에는 `scripts/release/release_artifact.py`와 `make package`를 유지한다고 결정했다.
그 책임은 배포 실행이 아니라 Artifact의 신원과 재현성이었다.

- Git에서 추적하는 Release Payload 식별
- 결정론적 Manifest 생성
- 패키지 파일 구성
- 실제 파일 바이트 검증

Release 패키지는 배포 상태 머신이 아니었다. 외부 자동화가 이를 전달·보관해도
Runtime 수렴 권한을 획득하는 것은 아니었다. **위 도구의 현재 상태는 ADR-0046을 따른다.**

### 4. 이미지 빌드 권한은 배포 권한과 분리한다

통합 vLLM 이미지의 빌드 입력은 배포와 독립적인 정책을 따른다.
정규화된 저장소 소스 Manifest는 공통 vLLM 이미지 권한 경계에 속하는
`scripts/lib/vllm_unified_image.sh`로 이동한다.

이 Manifest의 목적은 빌드 재현성과 Dockerfile `COPY` 대상의 완전성을
확인하는 것이며, 원격 Release 디렉터리를 비교하는 용도가 아니다.

불변 Registry Digest로 게시된 이미지는 운영자가 지정할 수 있는 유효한 입력으로 남는다.
로컬 생명주기는 이런 이미지를 다시 빌드하지 않고 유지한다.

### 5. Runtime의 초기 시작 상태는 로컬 생명주기가 소유한다

`configs/deploy_profiles.yaml` 및 `RUNTIME_STARTUP_PROFILE`은
전체 Stack `make up`에서 초기에 실행을 보류할 보조 Model Runtime을 선언한다.

일회성 시작 지시 값은 Runtime 고유 식별자를 사용한다.

- `RUNTIME_STARTUP_DEFERRED_KEYS`
- `RUNTIME_STARTUP_GENERATION`

이 값은 전체 Stack `make up` 내부에서 생성되며 영속 운영자 설정이 아니다.
기존 Runtime 상태 Schema v2의 `applied_release_id`는 원하는 Runtime 상태를
바꾸지 않은 채 Schema v3의 `applied_startup_generation`으로 이관된다.

### 6. Platform Bootstrap의 Release 식별자 — 대체됨

> 원격 Release Consumer 제거 후의 불필요한 호환성 코드 정리(2026-10-01)로
> 이 결정은 대체됐다. `platform.release_id`는 항상 `null`이었고 현재
> Control Plane Bootstrap 계약에는 포함되지 않는다. 이전 호환성 결정의 기록만 남긴다.

## Consequences

- 새로운 Runtime 기능에는 `apply_remote_release.sh` 구현이 필요하지 않다.
- 저장소가 소유하는 배포 생명주기가 로컬·원격 상태 머신 둘이 아닌 하나로 정리된다.
- 소스 패키징은 현재 저장소 권한이 아니며, ADR-0046에서 Git Commit/Tree를 소스 신원으로 규정한다.
- 외부 자동화는 플랫폼 정책을 복제하지 않고도 정규 로컬 생명주기를 원격에서 실행할 수 있다.
- 원격 자동 Release Rollback을 제거한다. 복구는 컴포넌트별 또는 운영자·Source Control이 소유한다.
- Runtime 초기 시작 지시 값의 명칭은 배포·Release 식별자와 독립적이다.
- Prompt Injection Detector의 자원 제약 Topology를 별도 원격 수렴 경로 없이
  하나의 유효 Runtime 생명주기에서 구현할 수 있다.

## Removed implementation

- `scripts/deploy/deploy_compose_release.sh`
- `scripts/deploy/apply_remote_release.sh`
- `scripts/deploy/runtime-bin/python3.12`
- `scripts/lib/deploy_request_policy.sh`
- `scripts/lib/deploy_env.sh`
- `scripts/lib/deploy_recreate_policy.sh`의 원격 전용 부분

## Non-goals

- 소스 전달·패키지 제거에 대한 최종 결정은 ADR-0046이 소유한다.
- 불변 이미지 Digest 제거
- 외부 인프라 또는 Orchestration 도구 대체
- 새 Cluster Scheduler 도입
- 이 결정에서 Runtime Controller 또는 Main Model Control의 변경 계약 수정
