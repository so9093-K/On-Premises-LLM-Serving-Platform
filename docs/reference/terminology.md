# Canonical Terminology

이 문서는 프로젝트의 사용자-facing 문서, Control Plane Console, API 설명과 새 설정 이름에 사용할
표준 용어를 정의한다. 코드·Compose·환경변수의 기존 식별자는 호환성 계약일 수 있으므로, 표시
용어와 안정 식별자를 구분한다.

## 원칙

1. **역할을 이름에 쓴다.** `helper`, `adapter`, `secondary`처럼 관계만 나타내는 이름보다
   `Gateway`, `Runtime Controller`, `Embedding Runtime`처럼 책임을 드러내는 이름을 쓴다.
2. **표시명과 식별자를 분리한다.** 사람이 읽는 이름은 개선할 수 있지만, API path·service key·env key는
   migration 없이 바꾸지 않는다.
3. **원하는 상태와 실제 상태를 구분한다.** `desired state`와 `observed state`를 섞지 않는다.
4. **검증 수준을 다른 상태 의미와 섞지 않는다.** Main Model은 기술적 `Compatibility`와
   실제 장비 검증 여부인 `Qualification`을 별도 축으로 두고, Deployment Target은
   `Implementation Status`와 `Qualification`을 별도 축으로 둔다. Main Model config와
   Admin API는 같은 canonical 상태 vocabulary를 사용한다.
5. **위험한 동작은 효과를 설명한다.** `force`처럼 구현 중심 표현만 버튼에 노출하지 않고 실제 영향
   (예: 다른 runtime 자동 중지 허용)을 설명한다.
6. **영문 제품명은 `On-Premises`를 사용한다.** `On-Premise`는 새 문서·표시명에서 사용하지 않는다.

## Canonical terms

| Canonical term | 의미 | 기존/내부 식별자 |
|---|---|---|
| **On-Premises LLM Serving Platform** | 제품명 | repository: `On-Premises-LLM-Serving-Platform` |
| **Gateway** | 외부 API 진입점. 요청 검증, 인증, routing과 응답 처리를 담당 | `gateway` |
| **Control Plane** | runtime·configuration·model profile을 운영하는 관리 계층 | `/admin/*`, Console |
| **Control Plane Console** | Control Plane API를 same-origin으로 사용하는 first-party 운영자 UI | `/admin/console/` |
| **Configuration Plane** | operator-owned 설정의 metadata, effective value, Plan/Apply/Verify와 history를 관리하는 계층 | `/admin/configuration/*` |
| **Runtime Controller** | runtime lifecycle, Main Model 전환, reconciliation과 Docker 제어를 담당 | service ID `runtime-controller`, telemetry/module identifier `runtime_controller`, Python client `runtime_controller_client` / `RuntimeControllerClient` |
| **Model Runtime** | 실제 model inference/embedding/detection을 수행하는 실행 단위 | vLLM/MLX runtime |
| **Main Model Runtime** | `local-main` 요청을 수행하는 주 generation runtime | `main-llm-vllm` |
| **Embedding Runtime** | embedding과 dense retrieval scoring에 사용하는 runtime | `embedding-vllm` |
| **Korean Embedding Runtime** | 한국어 retrieval 기본 embedding runtime | `embedding-ko-vllm` |
| **Prompt Injection Detector Runtime** | prompt injection/leaking 신호를 생성하는 model runtime | runtime/config key `prompt_injection_detector`, service-registry key `prompt_injection_detector_runtime`, Compose service `prompt-injection-detector-runtime`, public model alias `risk-prompt`, operator env `PROMPT_INJECTION_DETECTOR_*` |
| **Risk Signal Service** | PII·Secret·Prompt detector 결과를 신호 계약으로 정규화. 최종 allow/block 정책은 소유하지 않음 | service ID `risk-signal-service`; Python/config identifier `risk_signal_service`; operator env `RISK_SIGNAL_SERVICE_*` |
| **Main Model Profile** | Main Model의 model revision, runtime image, command, capability와 request policy 조합 | `configs/main_model_profiles.yaml` |
| **Public Model Alias** | client가 고정적으로 사용하는 model 이름 | `local-main` |
| **Deployment Target** | platform/backend/lifecycle ownership 조합을 고르는 안정 설정 ID | `DEPLOYMENT_TARGET` |
| **Runtime Startup Profile** | full-stack 기동 직후 어떤 non-main runtime을 시작 상태로 둘지 정하는 preset | `RUNTIME_STARTUP_PROFILE`, `configs/deploy_profiles.yaml` |
| **Access Profile** | 사용자가 선택하는 접근 의도(local/private/edge) | `ACCESS_PROFILE` |
| **Desired State** | Control Plane이 수렴시키려는 runtime 상태 | `desired_state` |
| **Observed State** | 실제 container/runtime에서 관측한 상태 | `observed_runtime`, `container_status` |
| **Compatibility** | Main Model Profile이 현재 deployment/runtime 조합에서 기술적으로 가능한지 나타내는 축 | `compatibility.status` |
| **Implementation Status** | Deployment Target 자체가 실행 가능한 구현 상태인지 나타내는 축 | `implementation_status` |
| **Qualification** | 특정 Main Model 또는 Deployment Target을 maintainer가 실제 장비에서 검증했는지 나타내는 축 | `qualification.status`, `qualification_status` |
| **운영 활동(Activity)** | 최근 runtime/model/configuration 변경 기록을 모아 보는 Console 화면 | API object는 `operation` 유지 |
| **Playground** | 배포 feature별 공개 API 작업 화면(Chat·Embedding·Risk)을 묶은 Console 화면 | `/admin/console/playground`, ADR-0056 |
| **Playground · Chat** | 공개 Chat Completions API로 capability-aware 모델 동작을 확인하는 작업 화면 | `/admin/console/playground/chat`, ADR-0047; ADR-0041은 대체된 과거 결정 |
| **Verification Details** | apply/switch 후 실제 상태가 기대 상태와 일치했는지 확인한 정보 | 기존 UI 문구 operation evidence |

## 사용자-facing에서 피할 표현

| 피할 표현 | 이유 | 대신 사용 |
|---|---|---|
| **Admin Sidecar** | 독립 control service를 Kubernetes식 sidecar로 오해할 수 있음 | Runtime Controller |
| **Secondary Runtime** | 역할을 설명하지 못하고 Main과의 상대 관계만 표현 | Model Runtime 또는 구체 역할명 |
| **Risk Adapter** | 신호 생성/정규화 역할이 드러나지 않음 | Risk Signal Service |
| **risk-prompt** (표시명) | 탐지 대상이 불명확 | Prompt Injection Detector |
| **Deploy Runtime Profile** | deployment 전체 profile처럼 보임 | Runtime Startup Profile |
| **operation evidence** | 내부 영속성 구현 용어에 가까움 | Verification Details / Activity |
| **force** (단독 버튼) | 실제 영향이 드러나지 않음 | 필요한 runtime 자동 중지 허용 |

## 레거시 이름과 활성 호환성 식별자 구분

이 표의 이름은 모두 삭제 후보를 뜻하지 않는다. 변경 기준과 현재 소유권은
[ADR-0030](../adr/0030-target-architecture-state-and-artifact-boundary.md),
[ADR-0046](../adr/0046-source-transport-is-not-platform-authority.md),
[설정 기준](../05_configuration.md)을 따른다.

| 예전 표기 또는 구현 식별자 | 현재 소유권과 처리 |
|---|---|
| `admin-sidecar` / `admin_sidecar` | 과거 아키텍처 설명에서만 사용한다. 현재 운영자용 명칭은 **Runtime Controller**이고 활성 service는 `runtime-controller`다. |
| `MAIN_LLM_*` / `main_llm` / `main_llm_vllm` | `MAIN_MODEL_*`은 operator-facing 설정 namespace다. `main_llm` 모델 서비스 key와 `main_llm_vllm` 식별자는 실제 Registry·호환 소비자가 있으므로 문자열 일괄 치환 대상이 아니다. Runtime validator의 `--main-llm-base`도 현재 지원되는 CLI 옵션이다. |
| `risk_prompt` / `risk-prompt` | 내부 Runtime은 `prompt_injection_detector` / `prompt-injection-detector-runtime`로 구분하지만 `risk-prompt` 공개 모델 alias와 이전 state의 migration 입력은 의도적으로 유지한다. |
| `RISK_VLLM_IMAGE` / `EMBEDDING_KO_VLLM_IMAGE` | 활성 persistent image 설정이 아니다. 공유 Runtime은 `VLLM_IMAGE`를 사용하고 `env_contract.yaml:removed_keys`는 예전 호스트 `.env` 정리 목적이다. |
| 과거 모델 VRAM·vLLM 측정 주석 | **작성 당시 특정 장비와 모델 조합의 검증 이력**이다. 현재 활성 Runtime 상태와 엔진 기능은 실제 관측·활성 Profile·`GET /v1/models`가 소유한다. |

현재 공개 API·운영 오류 안내·CLI help에는 오래된 이름을 추천 설정처럼 사용하지 않는다.
이전 설치 상태를 실제로 변환하는 migration 코드와 재현 가능한 이력은 무조건 삭제하지 않는다.

### Process inputs

- `RUNTIME_STARTUP_PROFILE`이 full-stack compose-up의 유일한 operator-facing startup profile input이다.
- `RUNTIME_STARTUP_DEFERRED_KEYS`와 `RUNTIME_STARTUP_GENERATION`은 compose-up이 Gateway에 전달하는 내부 one-shot directive이며 persistent `.env` key가 아니다.

## 헷갈리기 쉬운 env key

다음 key는 이름만 보고 의미를 추측하면 잘못 쓰기 쉬우므로 별도 의미 계약으로 유지한다.

| Key | 실제 의미 | 주의 |
|---|---|---|
| `MAIN_MODEL_ALIAS` | client-facing **Public Model Alias**. 현재 기본값은 `local-main` | upstream model/checkpoint 이름이 아니다 |
| `GATEWAY_HOST` | host에서 직접 실행하는 Gateway process의 listen address | Compose host publish address가 아니다 |
| `GATEWAY_BIND_ADDR` | Compose가 Gateway port를 host에 publish할 때 bind할 address | application process listen address와 구분 |
| `API_KEYS` | Gateway가 허용하는 Bearer key 집합 | server-side accepted credential set |
| `API_KEY` | smoke/ops client가 요청에 사용할 단일 Bearer key | 기본 생성 경로에서는 `API_KEYS`의 첫 key와 같지만 역할은 다르다 |
| `ADMIN_API_KEYS` | Admin API가 허용하는 Bearer key 집합 | server-side accepted credential set |
| `ADMIN_API_KEY` | 운영 도구가 사용할 단일 Admin credential이자 일부 내부 secret projection의 source | plural key set과 역할을 구분한다 |

## 식별자 변경 정책

기존 API field, endpoint, Compose service, environment key를 바꿀 때 기본 정책은 **canonical contract로 직접 cutover**하는 것이다.
compatibility layer는 다음 중 하나가 구체적으로 성립할 때만 둔다.

1. 기존 persistent state/config 값을 읽지 못하면 업그레이드 과정에서 데이터 또는 운영 의도가 손실된다.
2. OpenAI-compatible API처럼 외부 표준 호환 자체가 제품 기능이다.
3. 버전 정책에서 안정화했다고 명시한 공개 계약을 실제 외부 consumer가 사용한다.

이 경우에도 runtime dual-read를 영구 계약으로 만들지 않는다. 가능한 경우 `setup_env.py --sync-env` 같은 migration 도구가
기존 값을 canonical 형태로 한 번 옮기고, bridge에는 제거 조건을 함께 기록한다. 단순히 "기존 사용자가 있을 수 있다"는
추측이나 참조 수가 많다는 이유만으로 alias를 유지하지 않는다.

사용자-facing 표시명과 안정 식별자는 각각 의미에 맞게 canonicalize한다. `/admin/*`은 Control Plane
관리 API namespace이고, `/v1/risk/*`는 Risk 도메인을 표현하는 public API다.

API 오류 메시지·OpenAPI 설명/예제·CLI help·Console help·운영 설정의 description도
사용자-facing 표시 계약에 포함한다. 이 surface에서는 `Runtime Controller`,
`Risk Signal Service`, `Prompt Injection Detector Runtime` 같은 canonical term을 사용하고,
`runtime-controller`, `risk-signal-service`, `risk_signal_service`, `prompt-injection-detector-runtime` 같은 값은 실제 identifier를 정확히
가리켜야 할 때만 code formatting과 함께 노출한다.
