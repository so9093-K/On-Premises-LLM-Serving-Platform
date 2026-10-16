# ADR-0046: 소스 전달은 플랫폼 배포 권한이 아니다

## Status

Accepted

## Date

2026-10-01

## Context

ADR-0037은 저장소가 소유하던 원격 Release 상태 머신을 제거하면서도,
결정론적인 소스 ZIP과 Release Manifest는 별도의 Artifact 책임으로 남겼다.

원격 배포가 제거된 후 해당 패키지는 저장소 내부의 배포 소비자가 없었다.
남아 있던 구성은 전용 Payload 식별·구성 도구, ZIP Writer·Verifier,
Release Manifest·Provenance 포맷, 전용 단위 테스트와 문서,
그리고 패키지를 만들었다가 버리는 CI 단계였다. GitHub Releases에도
그 형식으로 게시된 Release Asset은 없었다.

플랫폼에는 패키지가 중복해서 담던 정보를 이미 소유하는 별도 Source of Truth가 있다.

- 소스 신원은 Git Commit/Tree가 식별한다.
- 프로젝트·Python 패키지 버전은 `VERSION`과 `pyproject.toml`이 식별한다.
- Platform 및 통합 vLLM 이미지의 내용은 불변 Registry Digest로 승격·식별한다.
- Runtime 수렴은 배포 대상별 로컬 생명주기와 Control Plane이 소유한다.
- CI는 애플리케이션·계약·Control Plane Frontend 및 실행 가능한 Platform 이미지를 검증한다.

저장소 고유의 소스 전달 형식을 유지해도 배포 정확도가 달라지지 않으므로
불필요한 Artifact 생명주기만 추가되는 것이다.

## Decision

### 1. 저장소는 소스 ZIP 전달 계약을 소유하지 않는다

`make package`, `scripts/build/package_release.sh`, Release Payload
식별·구성 도구와 전용 테스트를 제거한다.

저장소는 `RELEASE_MANIFEST.json`, `RELEASE_PROVENANCE.json` 또는 별도의
소스 아카이브 신원 포맷을 정의하지 않는다.

### 2. 소스 신원은 Git이 소유하고 외부 전달 도구는 Archive를 만들 수 있다

소스 Snapshot은 Git Commit/Tree로 식별한다.
외부 자동화·감사 절차·사용자가 아카이브를 필요로 한다면 선택한 Git 소스로부터
플랫폼 계약 밖에서 생성한다.

이 방식은 두 번째 배포 권한을 만들지 않는다.
호스트에 소스를 적용하는 작업은 여전히 정규 배포 대상별 로컬 생명주기로 수렴한다.

### 3. 배포 가능한 Artifact의 신원은 불변 이미지 Digest다

Platform과 Model Runtime 이미지는 기존 빌드·게시 권한 경계를 유지한다.
게시된 불변 Registry Digest가 배포에서 사용하는 이미지 내용을 식별한다.

`scripts/lib/source_provenance.sh`는 Platform 이미지의 Build Label에
소스 Revision과 Clean/Dirty 상태를 기록하므로 유지한다.
단, 더 이상 소스 ZIP Manifest 생성용으로 사용하지 않는다.

### 4. 패키지 전용 프로세스 입력은 유효 설정이 아니다

Runtime·CI·운영자 명령은 패키지 이름 또는 출력 경로 Override를 소비하지 않는다.
기존 `.env`에 사용하지 않는 값이 남지 않도록 정리용 Tombstone은 유지할 수 있지만
활성 설정 계약으로 해석하지 않는다.

기존 `EXPOSURE_MODE` 이관 검사는 이와 무관하므로 계속 Fail-Closed한다.
과거 네트워크 노출 의도를 새 설정으로 조용히 재해석하는 일을 막기 때문이다.

### 5. CI는 사용하지 않는 전달 구현이 아니라 실제 제품 Artifact를 검증한다

필수 CI Gate는 다음 계약을 계속 검증한다.

- 지원하는 Python 버전의 애플리케이션 및 저장소 계약
- Control Plane 소스와 생성 산출물
- Platform 이미지 빌드와 Smoke Test

사용하지 않는 소스 아카이브 코드의 동작을 증명하기 위해 아카이브를 만들지 않는다.

### 6. 제거된 Release Orchestration의 Compose 권한 우회를 남기지 않는다

정규 생명주기는 기존 Compose 프로젝트에 변경을 가하기 전에
그 프로젝트가 현재 Checkout 소유인지 확인한다.
이전 `ALLOW_SHARED_COMPOSE_PROJECT` 예외는 제거된 Release Orchestration에
속하므로 Checkout 소유권 검증을 일반적으로 우회하는 기능으로 남기지 않는다.

외부 자동화에서 여러 Checkout을 의도적으로 운영하려면
소유권 검사를 끄는 대신 서로 다른 `COMPOSE_PROJECT_NAME`을 사용해야 한다.

## Consequences

| 긍정적 결과 | 제약 또는 트레이드오프 |
|---|---|
| 배포 소비자가 없는 두 번째 Artifact 생명주기를 제거한다. | 외부 소비자는 제거된 자체 ZIP/Manifest 형식에 의존할 수 없다. |
| CI 시간과 테스트 범위를 실제 제품·Runtime 계약에 맞춘다. | 외부 자동화가 소스 Archive를 필요로 하면 해당 전달 수단을 직접 선택·관리해야 한다. |
| Git 소스 신원과 불변 이미지 신원의 권한을 명확히 분리한다. | 저장소가 자체 파일별 Hash를 기록한 소스 Payload Manifest를 제공하지 않는다. |
| 패키지 전용 호환성 코드와 문서의 유지 비용을 줄인다. | 과거 ADR/CHANGELOG에는 제거된 형식이 당시 기록으로 남아 있을 수 있다. |

## Operational impact

개발, `make up`, Control Plane 상태 변경, 이미지 빌드 및 Runtime 검증은 달라지지 않는다.

`make package` 명령은 존재하지 않는다. 소스 소비자는 선택한 Git Revision을 사용하고,
배포 소비자는 기존 대상별 생명주기와 불변 이미지 참조를 사용한다.

## Migration notes

- `make package`를 호출하던 외부 자동화는 선택한 Git Revision을 직접
  Archive/Checkout하거나 Source Control 서비스의 아카이브 기능을 사용해야 한다.
- 실제 소비자와 실패 상황이 안정된 Archive 계약을 요구하기 전까지
  저장소가 소유하는 소스 전달 도구를 다시 도입하지 않는다.
- 일반적인 `.env`의 삭제된 키 정리는 과거 패키지·배포 전용 키를 삭제할 수 있으나,
  이를 유효 설정처럼 취급하지 않는다.

## Related

- [ADR-0037](0037-local-lifecycle-deployment-authority.md)
- [ADR-0039](0039-operator-intent-lifecycle-and-diagnostics.md)
- [9. 자동화 경계](../09_cicd.md)
- [10. 배포](../10_deployment.md)
