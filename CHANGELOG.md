# 변경 이력

이 파일은 사용자와 운영자에게 의미 있는 변경·호환성·마이그레이션을 기록한다. 내부 구현과 수정 과정은 Git commit/PR 이력을 따른다.

## [Unreleased]
- Controller 장애·Gate 차단 중 `/v1/models`는 논리 모델 목록을 유지하되 확인되지 않은 Main 실행 한도·Backend를 광고하지 않고 정책 상태를 구분한다.
- 미지원 이전 Target은 설정 변경 시 명확히 거부한다. 자동 전환·상태 이전이나 인증 설정을 변경하는 호환 계층은 추가하지 않는다.
- 독립 CPU Compose를 위해 남은 `cpu_main_llama` 서비스 선언을 제거한다.

### Added

- 모델 없이 Gateway·Control Plane·PII/Secret Risk를 제공하는 `linux-core`, 외부 llama.cpp를 연결하는 `linux-cpu-static`, Runtime Controller가 관리하는 CPU/GPU Main Model을 제공한다. 관리형 Linux에서는 CPU/GPU 실행 정책을 선택할 수 있다.
- Gateway가 OpenAI 호환 `/v1/responses`와 Chat·Embedding·Retrieval·Risk API를 제공하며, 실제 지원 기능과 요청 한도는 활성 모델의 `/v1/models` 계약을 따른다.
- Control Plane Playground에서 Chat·Embedding·Risk 및 Retrieval 문서 관련도 순위를 실행하고, 전송한 요청의 cURL·Python·Node.js 재현 코드를 내보낼 수 있다. Chat은 멀티모달 예제, Streaming·Tool Calling·구조화 출력을 지원하는 모델에서 해당 기능을 제공한다.
- Control Plane에서 Main Model 전환 검토·작업 이력·Runtime/GPU 상태·설정 적용 결과를 확인한다. Runtime 전환은 Plan/Apply와 결과 검증을 사용하며, 오래된 Plan은 거부한다.
- `ACCESS=edge` 환경에서 선택적으로 Tailscale Serve와 Nginx를 통해 관리자·팀원 API를 사설망으로 분리할 수 있다. 공개 인터넷 배포를 자동 구성하지 않는다. ([원격 접속](docs/guides/remote-access.md))
- Grafana·Loki 기반 요청 로그와 Gateway 지표, 최근 요청량·지연·거부 사유 및 GPU/Runtime 관측 화면을 제공한다. 수동 AIPerf 실측 자료는 운영 지표나 성능 보장과 분리해 보관한다. ([관측성](docs/11_observability.md), [성능 실측](docs/resources/README.md))

### Changed

- Runtime Controller 관리형 CPU/GPU Main Model에서 서버 문맥·최대 출력 토큰의 직접 변경을 지원한다. 모델 신원은 유지하고 Gateway 한도와 실행 엔진 인자를 동기화하며, 기존 전환·실패 복구·재시작 복원 경로를 재사용한다. 복구에 성공한 실패 구성은 정리하고, Rollback 실패 시에는 관측 신원을 보존해 Gate를 닫는다. 관리형 CPU/GPU는 하나의 Runtime Controller가 소유한다.
- Playground Chat은 시작 예제를 기본으로 보여주며, 대화 영역만 스크롤해 입력창 위치를 유지한다. 지원되지 않는 예제도 미지원 사유를 포함해 표시한다. 요청별 최대 출력 토큰은 입력창에서 조정하며 서버 실행 한도와 구분한다.
- 메인 모델 화면은 동일 모델·Revision·엔진의 실행 프로필을 하나의 모델 아래 묶고, 프로필 세부 정책을 펼쳐 확인한다. Controller 관리형 CPU/GPU의 고정 실행 정책에서는 선언된 구성 선택뿐 아니라 문맥·최대 출력 한도를 직접 변경할 수 있다.

- 운영 개요는 Core의 모델 부재, 관리형 CPU/GPU와 외부 Runtime의 권한을 구분한다. 실제 모델 상태를 관측하지 않는 환경은 준비 완료로 표시하지 않는다.
- Risk·Embedding·Retrieval은 마지막 요청 결과와 현재 수정된 입력을 명확히 구분하며, Risk 재검사 중에는 이전 성공 결과를 현재 실행 결과로 표시하지 않는다.
- 런타임 시작·중지의 영향 검토 및 적용 결과로 키보드 포커스를 이동하고, 운영 활동에서 기존 Runtime·Configuration History API의 이전 페이지를 직접 탐색할 수 있다.

- CPU llama.cpp는 하나의 Qwen3 GGUF 기준 프로필(8,192/4,096)을 사용한다. CPU 고정 모드에서 512~16,384 문맥과 문맥 이하의 최대 출력을 직접 설정하며, 16K는 성능 검증 결과가 아닌 명시적 정책 상한이다.
- Playground Chat의 초안·첨부·모델·요청 설정은 같은 탭에서 화면 이동 시 유지한다. API 키 교체·삭제 시 진행 중 요청을 중단하고 Chat 세션을 정리한다. 변경된 설정을 표시하고 Risk 예제의 입력 교체는 확인을 요구한다. Embedding·Risk 입력은 화면 이탈 시 삭제한다.
- 메인 모델 상태 → 서버 한도 설정 → 영향 확인 → 전환 결과로 운영 동선을 정리한다. Grafana에서는 공개 API 요청과 내부 호출을 구분하고, GPU 사용률·vLLM 처리율·Loki 토큰 합계를 설명하며 요청 경로·조회 기간을 유지해 로그로 이동한다.

- `make up`은 Target별 실제 서비스 Readiness로 기동을 판정한다. 일반 전체 스택은 Main Chat 요청 가능 여부도 확인하며, 추가 기능별 검증은 독립된 `make smoke`가 담당한다. `make build-image`와 `make image-smoke`도 분리하고 CI에서는 각각 검증한다.
- 로컬 Platform·vLLM 이미지는 각각의 실제 실행 입력으로 재사용을 결정한다. README·LICENSE·NOTICE의 변경·누락, Git 상태, 별도 Smoke 스크립트는 불필요한 재빌드 사유가 아니다. 기존 이미지에 실행 해시가 없다면 다음 기동 시 한 번 갱신될 수 있다. ([ADR-0062](docs/adr/0062-runtime-artifact-reuse.md))
- 포트 대역은 `.env`의 `PLATFORM_PORT_BASE`가 소유한다. 신규 설치는 `make up TARGET=<target> PORTS=9600`, 기존 환경은 `make ports BASE=9600` 후 `make up`으로 적용한다. 변경 시 Gateway·모델 컨테이너가 재생성되어 일시적인 중단이 생길 수 있으며, 소스 수정·Node.js·전체 테스트는 필요하지 않다. ([ADR-0064](docs/adr/0064-port-band-is-deployment-configuration.md))
- 관리형 Linux의 기본 정책은 GPU 우선·CPU 복구이며 GPU 복귀는 운영자가 검토·적용한다. 자동 전환 또는 CPU/GPU 고정 정책은 Console에서 선택하며, 기존 영속 정책은 보존한다. GPU 준비 실패 중에도 가능한 Core·CPU·관측 기능을 유지한다. ([실행 정책](docs/guides/adaptive-runtime.md))
- Main Model의 실제 image·revision·실행 인자·리소스 정책이 선언된 Profile과 일치해야 요청 Gate를 개방한다. Runtime 재시작·모델 전환·Rollback 후에는 현재 인스턴스의 신원과 실제 응답을 재검증한다. Controller를 관측할 수 없으면 관리형 Main의 `/ready`는 준비 완료를 주장하지 않는다.
- Runtime 시작·중지는 검토한 `plan_digest`를 Apply 시 재확인하며, GPU Admission과 선행 Runtime의 영향을 다시 판단한다. 변동된 계획은 `409 RUNTIME_PLAN_CHANGED`로 거부한다. ([Runtime Plan/Apply](docs/reference/runtime_transition_plan.md))
- 사용자 가이드·Control Plane·Scalar API 문서를 작업 중심의 한국어 안내로 정리했다. 현재 지원 기능과 오류·준비 상태를 구분하며, Playground의 완료된 모델 응답은 제한된 Markdown으로 표시하되 HTML·외부 리소스를 실행하지 않는다.
- 프로젝트 운영 진입점은 `make up/status/logs/down/reset/purge` 중심이다. 변경된 설정과 포트, 준비되지 않은 서비스의 원인·진단 로그를 표시한다. 로컬 기동은 Git 저장소 메타데이터 없이도 가능하다.
- Python 의존성은 Platform과 별도 MLX Runtime의 `pyproject.toml`·`uv.lock`을 따른다. `make up`은 실행 의존성만 준비하고 개발 검증 도구는 별도 `make setup-dev`·`make check`가 소유한다.
- 기본 vLLM 런타임은 검토된 고정 이미지와 모델 패치를 사용한다. CUDA 12.9 후보는 명시적으로 빌드할 수 있지만 기존 운영 이미지 참조를 자동 변경하지 않는다.
- Runtime Controller·Risk Signal Service, 설정/접근 프로필, API 오류 코드 및 요청 기록의 책임 경계를 정리했다. 현재 환경변수와 지원 값은 [설정 가이드](docs/05_configuration.md)가 소유한다.

### Migration

- 기존 배포에서 `ACCESS_PROFILE`이 없다면 `make up ACCESS=local`(또는 `private`, `edge`)로 변경 내용을 먼저 검토하고, 적용 시에는 같은 명령에 `CONFIRM=access`를 추가한다. 과거 `EXPOSURE_MODE=master_open` 상태는 자동으로 이관하지 않는다. ([접근 설정](docs/05_configuration.md#59-인증과-노출-정책))
- 관리형 Linux는 `linux-nvidia-dynamic`만 지원한다. 삭제된 관리형 CPU·Adaptive Target을 기록한 기존 `.env`는 자동 전환하지 않으며, 실행 중인 구성을 `make down`으로 중지하고 `DEPLOYMENT_TARGET=linux-nvidia-dynamic`을 명시해 새 구성을 시작한다. 인증·모델 캐시를 임의로 삭제하지 않는다. ([실행 정책](docs/guides/adaptive-runtime.md))
- 새로운 실행 설정은 `MAIN_MODEL_*`, `RUNTIME_CONTROLLER_URL`, 공유 `VLLM_IMAGE`를 기준으로 한다. 이전 키를 직접 사용하는 자동화는 현행 설정을 확인해 갱신해야 한다. 기존 배포 환경의 설정 동기화는 `make up`이 담당한다. ([환경 설정](docs/05_configuration.md#510-환경-파일))
- Control Plane Bootstrap의 구 `control_mode=sidecar`·상태 projection과 Risk Signal Service의 과거 OpenAPI `operationId`에 의존하는 외부 클라이언트는 현행 응답·Schema에 맞춰 수정하거나 SDK를 다시 생성해야 한다. 모델·Runtime의 실제 지원 여부는 활성 API 계약으로 확인한다.


### Fixed

- Docker 관측 실패·GPU 예약 불확실성·전환 중 Runtime 변경에서 검증되지 않은 요청 Gate 개방과 잘못된 자원 해제를 차단한다.
- Chat·Responses Streaming의 부분 UTF-8 및 비정상 종료를 처리하고, 완료되지 않은 응답을 정상 완료로 기록하지 않는다.
- deferred Runtime을 초기 기동에서 불필요하게 시작하거나 필수 Smoke 대상으로 처리하던 경로를 수정했다.
- API의 실제 오류 코드·요청 필드 한도·모델별 입력 제한과 문서의 불일치를 바로잡았다.

### Removed

- 자체 성능 Benchmark/승격 체계와 Main Model qualification evidence 시스템을 제거했다. 현재 qualification은 유지관리자의 검증 선언이며, 실제 장비·성능 결과는 별도 기록으로 확인한다. ([ADR-0042](docs/adr/0042-remove-qualification-evidence-and-benchmark.md))
- 사용하지 않는 원격 Release orchestration, 구버전 migration 전용 별칭·도구, 중복된 `/redoc` 문서 화면을 제거했다. API 문서는 `/docs`와 `/openapi.json`을 사용한다.

### Security

- Gateway에는 Docker Socket 접근 권한을 부여하지 않고 Runtime Controller에 프로젝트 소유 컨테이너의 제어를 제한한다. Runtime의 직접 Host 노출은 별도 제한한다.
- 공개 API와 관리자·내부 API의 인증/노출 경계를 분리하고, 외부 응답에는 내부 디버그 정보나 민감한 관리 요청을 노출하지 않는다.

## [0.0.1] - 2026-05-20

### Added

- Gateway 중심의 chat, embedding, retrieval, risk signal API 계약과 운영 문서 기준선을 제공한다.
- 모델 catalog, model cards, runtime config, OpenAPI/JSON Schema, monitoring projection 검증 흐름을 포함한다.
- Docker/GPU full-stack 운영을 위한 compose, Prometheus, Grafana, runtime validation report 생성 흐름을 제공한다.

### Changed

- 관리형 Linux의 Main 실행 정책을 Console에서 자동·CPU 고정·GPU 고정으로 선택한다. 최초 `TARGET=auto`는 공통 구성에서 CPU부터 검증하며 GPU 준비 실패 중에도 Core·CPU·관측을 유지한다. 기존 배포는 선택한 엔진·인증·포트·캐시를 보존한다. ([실행 정책](docs/guides/adaptive-runtime.md), [ADR-0061](docs/adr/0061-managed-linux-execution-policy.md))

- CHANGELOG는 짧은 release history로 유지한다.

### Security

- 인증/인가 동작은 이 문서 재구조화에서 변경하지 않았다.
