# ADR-0059: 포트 대역 변경은 명시적으로 적용하고 기존 캐시를 보존한다

## Status

Accepted. ADR-0058의 변경 도구를 유지하고 기본 대역·이관 절차를 보완한다.

## Context

포트 정책을 중앙화하려는 목적과 기본 배포 주소 변경은 별개의 결정이다.
96xx 이관 이후 94xx로 되돌리는 과정에서 Compose의 캐시 볼륨 라벨 변경이
삭제 확인 질문을 발생시켰고, 출력이 로그로 전달되면서 기동이 무기한 대기했다.
일부 서비스만 새 포트를 적용한 상태와 선택형 Runtime의 중지를 장애로 안내하는 문제도 확인됐다.

## Decision

1. 기본 대역은 9400이다. `configs/services.yaml`의 `port_namespace.base`와 역할별
   `offsets`가 포트 정책의 원본이다. ADR-0058의 역할 순서는 유지한다.
2. 전체 대역 변경은 운영자/maintainer가 `make ports BASE=<대역>`으로 명시적으로 실행한다.
   저장소 업데이트와 `make up`을 대역 이관 승인으로 취급하지 않는다.
3. `PLAN=1`은 변경 포트와 파일 목록만 표시한다. 적용 시 설정·소스·문서와 생성물을
   함께 갱신하고 검증하며, 실패하면 기존 파일과 생성물의 존재 여부까지 복원한다.
4. `.env`의 Gateway/Grafana Host 포트 override와 전체 대역 변경을 구분한다.
   관리 대상 URL은 서비스 역할에 따라 authority의 포트만 변경한다. 외부 URL과 secret은 유지한다.
5. 파일 변경과 실행 서비스 수렴은 별도 단계다. 실행 환경은 `make up`으로 반영하고
   `make status`로 확인한다. 실행 상태의 원자적 전환이나 자동 rollback을 보장하지 않는다.
6. 기존 캐시 볼륨은 checkout 소유권·연결 컨테이너·볼륨 identity를 검증한 뒤
   external Compose override로 재사용한다. legacy 연결 증거는 checkout에 묶인 로컬 manifest에
   기록해 일반적인 down/up 이후에도 확인한다. 이 처리는 볼륨을 재생성하거나 purge 권한을 넓히지 않는다.
7. 로그로 출력되는 내부 실행 단계는 stdin을 닫는다. 숨겨진 삭제 질문을 운영자 입력으로
   승인하거나 무기한 대기하지 않는다. 미확인·타 checkout 볼륨은 오류로 중단한다.
8. 기동/상태 CLI는 `/ready`의 필수·선택 dependency 구분을 따른다.
   선택적으로 중지한 Runtime은 플랫폼 준비 상태를 실패로 바꾸지 않는다.

## Consequences

전체 대역 변경에는 개발 도구와 변경 diff 검토가 필요하다. 단순 접속 포트 변경에는 `.env`
override를 사용할 수 있다. Prometheus/OpenAPI/Console 산출물은 재생성하고 source drift를 검증한다.
외부 프록시·방화벽·클라이언트 주소는 운영자 책임이며, 과거 ADR과 촬영 증거의 포트는 보존한다.
명시적 소유권 라벨이 없는 legacy 캐시는 소유권 증거가 사라지면 자동 재사용·삭제하지 않는다.

## Validation

회귀 테스트는 계획 조회의 무변경, 같은 대역 재적용, 94xx→다른 대역→94xx,
secret/외부 URL 보존, 생성 실패 복구와 Host override를 다룬다.
Docker 호스트에서는 `RUN_DOCKER_LIFECYCLE_TESTS=1`로
`tests/contract/test_compose_volume_reuse_docker.py`를 실행해 실제 볼륨 파일과 identity 보존을 확인한다.
