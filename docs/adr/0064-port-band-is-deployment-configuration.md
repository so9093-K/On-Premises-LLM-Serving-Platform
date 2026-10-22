# ADR-0064: 포트 대역은 배포 설정이며 실행 입력에서 파생한다

## Status

Accepted. [ADR-0058](0058-port-namespace-policy.md)의 변경 도구와
[ADR-0059](0059-explicit-port-migration-and-cache-preservation.md)의 소스·생성물 갱신 절차를 대체한다.
역할별 offset, 기본 대역 9400, 외부 엔진 포트 제외, 명시적 변경 원칙은 유지한다.

## Context

다른 서비스가 94xx를 쓰는 서버에서 대역을 9600으로 옮기려던 운영자가 다음 순서로 막혔다.

- `GATEWAY_PORT`만 바꾸면 내부 주소는 94xx로 남았다. 내부 주소를 손으로 96xx로 바꾸면
  실제 수신 포트(94xx)와 어긋나 Gateway가 Main·Risk에 연결하지 못했다.
- `make ports`는 자기 스택이 쓰는 포트를 다른 프로그램의 충돌과 구분하지 못했다.
- 대역 변경이 70개 소스·문서 파일 치환, Console 재빌드, 전체 테스트로 구현되어 서버에
  Node.js와 개발 도구가 필요했다. 배포 산출물 검증(LICENSE 존재)이 실행 설정 변경까지 막았다.
- 이 사실들을 서비스를 내린 뒤에야 알게 됐다.
- `make status`와 기동 실패 메시지는 "Main readiness timed out"만 보여 주었고, 반복되는
  `/metrics` 401이 기본 로그를 채워 실제 원인을 가렸다.

포트 대역은 배포마다 다른 값이다. 저장소 소스가 그 값을 소유하면 배포 설정 하나를 바꾸는 데
개발 작업이 필요해지고, 설정의 일부만 바뀐 상태가 생긴다.

## Decision

1. `configs/services.yaml`의 `port_namespace`가 역할별 offset과 기본 대역을 소유한다.
   저장소의 설정·Compose·문서·생성물은 기본 대역 값으로 기록한다.
2. 배포의 대역 선택은 `.env`의 `PLATFORM_PORT_BASE` 하나다. Gateway·Runtime Controller·
   Risk·모델 Catalog·Runtime topology·Prometheus·Compose wrapper는 실행할 때
   `ai_model_serving.port_namespace`로 같은 역할의 포트를 계산한다.
   Compose는 `${PLATFORM_PORT_<ROLE>:-<기본값>}`을, Prometheus는 `.runtime/prometheus/`에
   생성한 설정을 사용한다. 설정 digest label이 바뀐 Prometheus만 다시 만든다.
3. `make ports BASE=<대역>`은 `.env`만 변경한다. 첫 설치와 한 번에 적용하는 경우는
   `make up PORTS=<대역>`을 사용한다. 저장소 업데이트나 인자 없는 `make up`은 대역을 바꾸지 않는다.
4. 두 경로 모두 서비스를 바꾸기 전에 Host 포트를 검사한다. 이 checkout의 컨테이너가 쓰는 포트는
   교체 대상이며, 다른 컨테이너·프로세스가 쓰면 이름과 함께 중단하고 `.env`와 서비스를 유지한다.
5. `main-llm-vllm`처럼 플랫폼이 실행하는 서비스의 `*_BASE_URL`은 대역 포트에서만 수신하므로
   `make up`이 대역과 어긋난 값을 바로잡고 변경한 키와 포트를 표시한다. 외부·loopback 주소,
   운영자가 지정한 `GATEWAY_PORT`·`GRAFANA_PORT`, 인증키는 바꾸지 않는다.
6. 실행 설정 검증은 배포 문서 파일(README·LICENSE·NOTICE)의 존재를 요구하지 않는다(ADR-0062).
7. Prometheus 관리자 토큰 파일은 기동마다 `.env`와 맞춘다. 같은 inode에 쓰므로 실행 중인
   Prometheus도 다음 수집부터 새 키를 사용한다.
8. `make status`와 기동 실패는 준비되지 않은 필수 dependency의 오류·내부 주소와 확인할 서비스
   로그를 표시한다. Gateway에 연결되지 않으면 컨테이너 상태와 아직 적용되지 않은 포트 변경을
   구분한다. 기본 로그는 같은 원인의 반복 이벤트를 한 줄로 묶는다.

## Consequences

- 대역 변경에 Git·Node.js·전체 테스트가 필요하지 않고 소스 diff가 생기지 않는다.
- 내부 주소를 `.env`에서 손으로 고쳐도 실행 주소와 어긋난 상태로 남지 않는다.
- 대역이 바뀌면 Compose 서비스는 새 설정으로 다시 만들어지고, Main 컨테이너는 Runtime
  Controller의 기존 drift 복구(같은 Profile로 재생성·검증)를 따른다. 짧은 서비스 중단이 생긴다.
- 저장소에 생성해 두던 `ops/prometheus/prometheus*.yml`은 실행에 쓰이지 않으므로 제거한다. Prometheus 설정은 `.runtime/prometheus/`에만 있다.
- 팀원 Nginx 설정은 `scripts/access/remote_access.py nginx-config`로 현재 대역에 맞춰 출력한다.

## Migration notes

`PLATFORM_PORT_BASE`가 없는 `.env`에는 다음 `make up`이 기본값 9400을 추가한다. 기존의
`GATEWAY_PORT`·`GRAFANA_PORT` 값은 그대로 사용한다. 이전 `make ports`로 저장소 소스를 96xx로
치환한 checkout은 소스 변경을 되돌린 뒤 `make ports BASE=9600`으로 같은 대역을 `.env`에 기록한다.

## Related

- [ADR-0039](0039-operator-intent-lifecycle-and-diagnostics.md)
- [ADR-0058](0058-port-namespace-policy.md)
- [ADR-0059](0059-explicit-port-migration-and-cache-preservation.md)
- [ADR-0062](0062-runtime-artifact-reuse.md)
- [운영 절차](../12_operations.md#포트-대역-변경과-기존-캐시)
