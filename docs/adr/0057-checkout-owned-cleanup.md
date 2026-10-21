# ADR-0057: 종료와 삭제를 checkout 소유권으로 제한한다

## Status

Accepted

## Context

Compose 프로젝트 이름은 다른 checkout에서도 사용할 수 있다. 컨테이너가 제거된 뒤에는
프로젝트 이름만으로 남은 볼륨의 소유자를 확인할 수 없다. macOS에서는 launchd가 남아 있으면
환경 파일 삭제 후에도 MLX 재시작을 시도한다.

## Decision

- Docker 조회와 종료는 `scripts/ops/compose_ownership.py`가 소유한다. 컨테이너는
  checkout 루트 또는 `ops/compose`의 정확한 working-directory 라벨로 식별한다.
- 새 네트워크·볼륨과 로컬 build image에는 `ai_model_serving.checkout` 라벨로
  정규화한 checkout 절대 경로를 기록한다. 이 값은 wrapper가 계산하며 `.env`에 저장하지 않는다.
- `down`은 해당 컨테이너와 라벨이 일치하는 네트워크만 제거한다. `purge`의 볼륨·이미지 삭제는
  checkout 라벨을 필수로 요구한다. 사용 중인 볼륨은 오류로 보존하고, 사용 중인 이미지는 보존한다.
- macOS 종료는 MLX 소유 모듈을 호출한다. launchd는 plist의 정확한 WorkingDirectory로
  소유권을 확인하고 bootout 뒤 해제 여부를 검사한다. 실패하면 Reset의 파일 삭제를 중단한다.
  다른 checkout의 Supervisor는 보존한다. stop/uninstall은 앱 의존성과 모델 설정을 요구하지 않는다.

## Consequences

프로젝트 이름만 같은 다른 checkout의 자원은 삭제되지 않는다. 기존 라벨 없는 Docker 자원은
자동 삭제되지 않으며, checkout 이동 시 이전 경로로 생성한 자원도 보존된다.

## Migration notes

기존 Docker 자원에 소유권 라벨을 추정해 추가하지 않는다. 라벨 없는 볼륨·네트워크·이미지는
운영자가 원본 checkout과 사용 여부를 확인한 뒤 별도로 정리한다. 일반 `down`은 모델 캐시를 유지한다.

## Related

- [운영 명령](../12_operations.md#1210-reset과-purge를-장애-복구와-혼동하지-않는다)
- [ADR-0020](0020-runtime-control-and-deployment-targets.md)
