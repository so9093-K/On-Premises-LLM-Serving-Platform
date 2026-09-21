# 1. 프로젝트 개요

AI Model Serving Platform은 Chat, Embedding, Retrieval, Risk Detection 기능을 하나의 Gateway API로 제공하고,
배포 target별 runtime lifecycle과 운영 상태를 함께 관리하는 온프레미스 모델 서빙 플랫폼이다.

Model inference backend는 deployment target에 따라 Linux/NVIDIA의 vLLM 또는 Apple Silicon의 MLX-VLM을 사용한다.
Gateway의 외부 API 계약은 backend와 분리하며, runtime lifecycle ownership과 제공 기능은
`configs/deployment_targets.yaml`의 target contract가 결정한다.

## 1.1 프로젝트 배경

모델마다 API 형식, 입력 modality, context, resource 사용량, runtime option이 다르다.
모델을 추가하거나 교체할 때는 runtime 설정뿐 아니라 resource admission, validation, artifact,
deployment topology와 운영자 설명까지 함께 관리해야 한다.

이 플랫폼은 모델별 차이를 Gateway와 설정 체계에서 흡수하고, 애플리케이션에는 일관된 API를 제공한다.
운영자는 target별로 허용된 Control Plane 기능만 사용하며, API 사용은 Scalar,
시간축 metrics/log 진단은 Grafana가 각각 소유한다.

```text
Client / Application
        │
        ▼
      Gateway
        │
        ├─ Main Model Runtime
        ├─ optional Model Runtimes
        └─ Risk Signal Service
        │
        ▼
Deployment Target Contract
  ├─ runtime backend
  ├─ lifecycle ownership
  ├─ capability surface
  ├─ resource policy
  └─ qualification state

Operator surfaces
  ├─ Scalar        → API reference / authenticated test request
  ├─ Control Plane → state / plan / apply / verify / history
  └─ Grafana       → metrics / logs / troubleshooting
```

## 1.2 Deployment Target과 전체 아키텍처

### 현재 target

Deployment capability의 Source of Truth는 `configs/deployment_targets.yaml`이다.

| Target | Runtime backend | Lifecycle owner | Control mode | 상태 | 주요 기능 |
|---|---|---|---|---|---|
| `linux-nvidia-dynamic` | `vllm-cuda` | Platform | `runtime_controller` | Implemented / Verified | Chat, Embedding, Retrieval, Risk, Runtime Control, Main Model switching, GPU admission |
| `linux-nvidia-static` | `vllm-cuda` | External | `static` | Implemented / Unverified | Chat |
| `macos-metal-static` | `mlx-vlm` | External | `static` | Implemented / Verified | Chat |

`static`은 macOS의 별칭이 아니다. static target은 Main runtime lifecycle을 외부 또는 native process가
소유하고 Gateway는 고정 OpenAI-compatible endpoint를 사용한다. Linux와 macOS가 같은 static serving 계약을
공유할 수 있다.

### 공통 경계

| 구성 요소 | 주요 역할 | Authority |
|---|---|---|
| **Gateway** | 외부 API, 인증, request validation, routing, admission | 공개 API와 request contract |
| **Runtime Controller** | managed runtime lifecycle, Main Model 전환, GPU budget admission, Docker 제어 | `runtime_control`이 활성인 target의 runtime mutation |
| **Model Runtime** | 실제 inference / embedding / detection | target별 vLLM 또는 MLX-VLM runtime |
| **Risk Signal Service** | Risk detector 호출과 signal 정규화 | Risk API의 detector orchestration |
| **Control Plane Console** | 현재 상태 설명, reviewed mutation, verification/history projection | 기존 Admin API의 first-party operator UI |
| **Scalar API Reference** | API contract 탐색, example, authenticated test request | OpenAPI 기반 API 사용 경험 |
| **Observability** | Metrics, logs, dashboard와 troubleshooting | Prometheus / Grafana / Loki / Alloy 및 target별 exporter |

Gateway는 Docker socket을 소유하지 않는다. managed runtime의 container lifecycle은 Runtime Controller가 소유한다.
static target에서는 Runtime Controller 기능을 노출하지 않으며 external/native runtime lifecycle이 authority를 유지한다.

### Linux/NVIDIA managed target

`linux-nvidia-dynamic`은 platform-owned managed runtime target이다.

```text
Client
  │
  ▼
Gateway
  ├─ Main Model vLLM
  ├─ Embedding vLLM
  ├─ Korean Embedding vLLM
  └─ Risk Signal Service ── Prompt Injection Detector Runtime

Runtime Controller
  ├─ Runtime start / stop
  ├─ Main Model profile switch
  ├─ GPU budget admission
  └─ Docker lifecycle

Observability
  └─ Prometheus · Grafana · Loki · Alloy · DCGM · cAdvisor
```

Main Model은 외부에 `local-main` alias를 제공하고, 내부에서는 허용된 Main Model profile 중
한 시점에 하나의 active profile을 사용한다.

### Static Main target

`linux-nvidia-static`과 `macos-metal-static`은 Main runtime lifecycle을 Gateway 밖에서 소유한다.

```text
Client
  │
  ▼
Gateway
  │
  ▼
Externally managed Main Runtime
  ├─ Linux/NVIDIA → vLLM
  └─ macOS/Metal  → MLX-VLM
```

static target은 model switching, GPU admission, Runtime Control을 제공한다고 가장하지 않는다.
Console은 target capability를 기준으로 해당 mutation surface를 숨기고 lifecycle ownership을 설명한다.

## 1.3 주요 특징

### Gateway 중심 API

애플리케이션이 사용하는 모델 기능은 Gateway에서 시작한다. 실제 route 집합은 deployment target capability에 따라 달라진다.

| 기능 | Gateway API |
|---|---|
| Model Listing | `/v1/models` |
| Chat | `/v1/chat/completions` |
| Responses | `/v1/responses` |
| Embedding | `/v1/embeddings` |
| Retrieval | `/v1/retrieval/*` |
| Risk Detection | `/v1/risk/*` |

Gateway는 외부 API 형식을 유지하면서 request parameter, 이미지·오디오·비디오 입력,
response 형식과 내부 runtime 차이를 처리한다. 현재 runtime이 실제로 공개하는 capability는
`/v1/models`와 target/profile contract를 기준으로 확인한다.

![Gateway API Reference](../assets/screenshots/scalar_api_reference.jpg)

*Scalar API Reference에서 현재 Gateway API의 endpoint, 요청·응답 schema와 example을 확인하고 인증된 Test Request를 실행할 수 있다.*

### Target-aware runtime lifecycle

Runtime lifecycle은 backend 이름이나 운영체제에서 추론하지 않는다.

| Target contract | 의미 |
|---|---|
| `control_mode=runtime_controller` / `lifecycle_owner=platform` | Platform이 runtime mutation과 reconciliation을 소유 |
| `control_mode=static` / `lifecycle_owner=external` | 외부/native runtime이 lifecycle을 소유하고 Gateway는 고정 endpoint 사용 |

따라서 Linux/NVIDIA와 macOS/Metal의 차이는 core/secondary가 아니라
runtime backend, capability, lifecycle ownership의 차이다.

### 설정 기반 운영

모델과 runtime 동작에 필요한 주요 값은 repository의 설정 파일에서 관리한다.

| 설정 영역 | 주요 파일 | 역할 |
|---|---|---|
| **Deployment Target** | `configs/deployment_targets.yaml` | backend, lifecycle owner, control mode, capability와 qualification state |
| **Model Catalog** | `configs/model_catalog.yaml` | 논리 모델 identity, capability와 public listing |
| **Main Model Profile** | `configs/main_model_profiles.yaml` | Linux/NVIDIA Main Model checkpoint/revision과 serving/runtime profile |
| **macOS MLX Runtime** | `configs/macos_mlx_runtime.yaml` | Apple Silicon MLX-VLM Main runtime profile과 실행 한도 |
| **Model Runtime** | `configs/model_serving.yaml` | 공통 backend/port/connectivity/admission과 non-main runtime option |
| **Runtime Topology** | `configs/runtime_topology.yaml` | feature-runtime 연결과 resource-aware composition constraint |
| **GPU Budget** | `configs/gpu_budgets.yaml` | managed runtime의 GPU memory budget과 전체 admission ceiling |
| **Service / Port** | `configs/services.yaml` | 서비스 identity, 내부 port와 연결 정보 |
| **Access / Exposure / Auth** | `configs/access_profiles.yaml`, `configs/exposure_profiles.yaml`, `configs/auth_profiles.yaml` | 접속 의도, host publish와 인증 정책 |
| **Monitoring** | `configs/monitoring.yaml` | Metrics, logs와 dashboard 관련 설정 |

설정 간 우선순위와 생성 artifact는 [5. 설정 체계와 Source of Truth](./05_configuration.md)에서 다룬다.

### Resource admission과 hardware 의미

managed Linux/NVIDIA target에서 Runtime Controller는 선언된 GPU budget과 active runtime 구성을 기준으로
start/switch admission을 판단한다.

GPU product name, UUID, driver, memory size는 관측값과 qualification provenance이며 지원 allowlist가 아니다.
새 GPU라는 이유만으로 별도 profile-level qualification을 요구하지 않는다. 실행 가능성은 deployment/runtime
compatibility, resource admission, selected profile contract와 runtime validation이 판단한다.

`resource_variant`는 GPU 제품 분류가 아니라 reference resource policy가 맞지 않을 때 사용하는
명시적 reviewed override다. 선택한 override가 profile에 없으면 reference policy로 조용히 fallback하지 않는다.

### Runtime artifact 경계

Platform application과 inference runtime artifact는 분리한다.

```text
Platform Image
  ├─ Gateway
  ├─ Risk Signal Service
  └─ Runtime Controller (managed target)

Linux/NVIDIA Runtime Artifact
  └─ Unified vLLM image + target/profile configuration

macOS/Metal Runtime Artifact
  └─ Native MLX-VLM environment + pinned runtime/model configuration
```

Production에서는 repository가 소유하는 image와 model revision을 고정된 입력으로 관리한다.
static external runtime은 자신의 lifecycle authority를 유지한다.

### 운영자 UX 경계

세 UI surface는 역할을 나눠 가진다.

| Surface | 역할 |
|---|---|
| **Scalar `/docs`** | API reference, request example, authenticated API 호출 확인 |
| **Control Plane `/admin/console/`** | 현재 상태 이해, Plan/Review/Apply/Verify, operation history |
| **Grafana** | 시간축 metrics, request/runtime logs, resource와 장애 진단 |

Control Plane은 Scalar의 API playground나 Grafana의 로그/그래프 탐색기를 다시 구현하지 않는다.
대신 현재 상태와 mutation 의미를 설명하고, 필요한 경우 해당 진단 surface로 연결한다.

## 1.4 실행 방식과 플랫폼 범위

### 실행 방식

| 방식 | 구성 |
|---|---|
| **app-only** | Gateway와 Risk Signal Service 중심 application 개발 환경 |
| **full-stack dynamic** | Linux/NVIDIA vLLM runtime, Runtime Controller와 observability를 포함한 managed serving |
| **static main** | 외부/native Main runtime endpoint와 Gateway를 연결하는 serving |

세부 lifecycle과 target별 명령은 [4. 실행 환경과 모드](./04_runtime_modes.md)에서 설명한다.

### 제공 기능은 target capability를 따른다

Chat은 현재 세 deployment target 모두 제공한다.
Embedding, Retrieval, Risk, Runtime Control, Main Model switching, GPU admission은
현재 `linux-nvidia-dynamic` target에서 제공한다.

이 차이는 target의 구현 누락을 추측하는 표시가 아니라 선언된 product capability다.
Console과 Gateway는 같은 target contract에서 기능 집합을 투영한다.

### 네트워크와 관측

`linux-nvidia-dynamic`의 `private_network` exposure에서는 Gateway와 Grafana를 host에 publish하고,
model runtime과 운영 backend는 Compose network 내부에 둔다.

static target은 `configs/deployment_targets.yaml`이 지정한 별도 Compose/native lifecycle을 사용한다.
특히 `macos-metal-static`은 native MLX-VLM runtime과 Gateway/Prometheus/Grafana/Loki/Alloy 경로를 조합하며,
NVIDIA GPU 전용 관측을 지원한다고 가장하지 않는다.

애플리케이션의 모델 기능은 항상 Gateway API를 기준 인터페이스로 사용한다.

## 다음 문서

- [2. 요청 처리 흐름](./02_request_flow.md)
- [3. 시스템 구성](./03_system_components.md)
- [4. 실행 환경과 모드](./04_runtime_modes.md)
- [5. 설정 체계와 Source of Truth](./05_configuration.md)
- [11. 관측성과 장애 대응](./11_observability.md)
