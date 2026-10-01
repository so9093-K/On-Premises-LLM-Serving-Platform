# 4. 실행 환경과 모드

AI Model Serving Platform은 개발 목적의 **app-only**, 전체 lifecycle을 소유하는
**full-stack dynamic**, 외부가 Main runtime lifecycle을 소유하는 **static main** 실행 방식을 제공한다.

- **app-only**: Gateway와 Risk Signal Service 중심의 application 개발 환경
- **full-stack**: vLLM runtime, Runtime Controller, observability를 포함한 전체 서빙 환경
- **static main**: 고정된 OpenAI-compatible Main runtime endpoint만 사용하는 최소 서빙 환경

실행 환경의 기능 집합은 `configs/deployment_targets.yaml`의 `DEPLOYMENT_TARGET`이 결정한다.
`static`은 macOS의 별칭이 아니며 Linux CUDA runtime도 static으로 연결할 수 있다.

### static main

static target에서는 Main runtime을 별도 process 또는 별도 supervisor가 기동·감시한다.
Gateway는 고정 Main endpoint로 Chat과 Streaming을 제공하고, Compose 내부의 local Risk Signal Service를 통해 PII/Secret detector를 제공한다.
`MAIN_MODEL_STATIC_PROFILE`은 외부 runtime과 동일한 검증된 Serving Profile로 반드시
고정하며, Gateway request limit과 capability 광고는 이 profile을 따른다.

```text
Client -> Gateway -> externally managed Main runtime
```

Embedding, Retrieval, Runtime Controller, 모델 전환과 GPU admission은 static feature set에 포함되지 않는다.
Risk Signal Service는 공통 `ops/compose/overrides/static.local-risk.yaml`에서 실행하며 PII/Secret은
in-process로 제공한다. Prompt Injection detector는 별도 model-backed capability라 static target에서는
비활성이고 Prompt 전용 endpoint는 `DETECTOR_DISABLED`를 반환한다. `/v1/models`에는 local Main만
남는다.

외부 Main runtime을 먼저 기동한 뒤 다음과 같이 Gateway만 실행한다.

운영자 `.env`에 `MAIN_MODEL_STATIC_PROFILE`과 `MAIN_MODEL_BASE_URL`을 지정한 뒤 실행한다.

```bash
make up
```

static target의 `make up`은 운영자 `.env`를 Compose interpolation source로 사용하고,
`configs/env_contract.yaml`의 target+service projection으로 Gateway와 Risk Signal Service
프로세스 env를 각각 생성한다. Gateway는 Main endpoint와 internal Risk token을 받고,
Risk Signal Service는 local detector와 internal/admin auth에 필요한 최소 키만 받는다.
두 서비스 사이의 내부 호출 edge 때문에 static target도 `internal_service_token_required=true`다.

`MAIN_MODEL_STATIC_PROFILE`은 실제 외부 runtime과 같은 target catalog의 profile이어야 한다.
Linux는 `configs/main_model_profiles.yaml`, Mac은 `configs/macos_mlx_runtime.yaml`을 읽는다.

#### Static local Risk

Linux/macOS static target은 같은 `static.local-risk.yaml` overlay를 공유한다. PII와 Secret은
Python in-process detector이므로 CUDA/Metal 여부와 무관하다. Prompt Injection detector는
`prompt_detection` capability와 별도 runtime provider가 있을 때만 effective topology에 들어온다.
이 경계는 [ADR-0044](./adr/0044-risk-capability-and-prompt-runtime-separation.md)를 따른다.

#### Apple Silicon MLX-VLM

Mac runtime은 Python 3.13.12의 앱 `.venv`와 분리된 native 환경 및 별도 lock을 사용한다. 모델 다운로드는
기동과 분리되어 있어 `metal-start`가 대용량 파일을 암묵적으로 받지 않는다.

```bash
HF_TOKEN=hf_xxx make up TARGET=macos-metal-static ACCESS=local
make status
```

고정 기본 profile은 Gemma 4 26B A4B QAT 4-bit와 QAT MTP assistant이며, 24,576 input,
8,192 generation, 이미지 1~4장, Thinking/MTP 활성, TurboQuant 비활성, 동시성 1이다.
5~8장은 기능 제외가 아니라 extended qualification 구간이다.

첫 `make up`은 target catalog에서 `MAIN_MODEL_STATIC_PROFILE`과 Docker Gateway가 native
runtime에 연결할 endpoint를 `.env`로 투영하고 필요한 image/model cache를 준비한다. `up`은 native MLX runtime을 프로젝트
소유 background process로 시작해 readiness를 기다린 뒤 static Compose를 기동한다.
`down`은 두 lifecycle을 역순으로 정리한다. 수동 `metal-*`, `build-image`,
`static-compose-*` 명령은 개별 계층을 진단할 때만 사용한다.

native runtime은 컨테이너가 아니라 호스트 프로세스라 Compose의
`restart: unless-stopped`에 해당하는 장치가 없다. 기본 기동은 project가 pid 파일로
추적하며, 프로세스가 죽으면 Gateway readiness가 dependency 실패로 보고하고 다시
올리는 것은 운영자의 몫이다. 원인은 `make status`가 실패할 때 함께 출력하는
`.runtime/metal/logs/` 아래 현재 소유자의 로그 꼬리에서 확인한다.

상시 운영이 필요하면 launchd supervisor를 선택 설치한다.

```bash
make metal-supervisor-install
make metal-supervisor-uninstall
```

설치하면 launchd가 재기동, 로그 경로 고정, `newsyslog` 회전을 함께 소유한다.

native runtime 로그는 `.runtime/metal/logs/` 아래에 있고 **수명주기 소유자마다 파일이
다르다**. project 기동은 `runtime.log`, launchd supervisor는 `supervisor.log`를 쓴다.
한 파일을 공유하면 "누가 먼저 만들었는가"가 동작을 가르기 때문이다 -- 저장소가
`~/Desktop`처럼 TCC 보호 경로에 있으면 launchd는 자기가 만든 파일만 열 수 있고,
다른 프로세스가 먼저 만든 파일에서는 job이 조용히 죽는다. 경로를 나누면 그 상태가
생길 수 없다. plist는
`server_command`가 만든 실행 명령을 그대로 감싸 `.runtime/metal/`에 생성하므로 model
revision이나 port를 따로 적지 않는다. 설치된 동안 수명주기 소유자는 launchd 하나이며
`up`/`down`/`status`는 pid 파일 대신 `launchctl`을 사용한다. supervisor를 설치해도
Gateway가 이 runtime을 제어하게 되는 것은 아니므로 target의 `lifecycle_owner`는
`external` 그대로다.

runtime의 stdout은 Alloy가 `job="native"`로 Loki에 보내므로 Request Log Explorer의
Runtime 원본 패널에서도 확인할 수 있다. supervisor를 설치하면 crash가 자동으로
복구되어 눈에 띄지 않게 되는데, 그 이력이 남는 곳이 여기다. 요청 이벤트의 신뢰
경로(`job="application"`)와는 분리돼 있다.

Mac static override는
Gateway, MLX JSON metrics exporter, Prometheus와 `메인 런타임 상태 (Apple Silicon)` Dashboard를 함께 띄운다.
MLX의 `/metrics`가 JSON이므로 기존 vLLM Prometheus scrape를 재사용하지 않는다.
Mac 로컬 기본은 `PLATFORM_IMAGE`를 registry에서 pull하지 않고 `make build-image`의
현재 arm64 산출물을 사용한다. Registry image를 쓰는 경우에만 `PLATFORM_PULL_POLICY`를
명시한다.

이 문서는 각 서비스가 실제로 어떻게 실행되고 연결되는지, 그리고 어떤 기준으로 준비 상태를 판단하는지를 설명한다.

구성 요소별 책임은 [3. 시스템 구성](./03_system_components.md), 설정 파일과 값의 우선순위는 [5. 설정 체계와 Source of Truth](./05_configuration.md), 모델 전환과 GPU 운영 절차는 [6. 모델 운영](./06_model_operations.md)에서 다룬다.

---

## 4.1 실행 모드

### app-only

app-only는 GPU와 vLLM runtime 없이 Gateway와 Risk Signal Service를 로컬 process로 실행하는 개발 모드다.

```text
Developer Host
│
├─ Gateway       localhost:9400
└─ Risk Signal Service  localhost:9405
```

주요 실행 명령은 다음과 같다.

```bash
make init-env-local
make up
make status
```

app-only는 다음 작업에 적합하다.

- Gateway / Risk Signal Service startup 확인
- API routing과 request validation 개발
- 인증과 error mapping 로직 확인
- OpenAPI / schema 개발
- mock 또는 별도 upstream을 이용한 application 테스트

실제 model loading과 inference, target별 resource/lifecycle 검증은 선택한 deployment target에서 수행한다. Linux/NVIDIA managed runtime의 GPU resource와 Runtime Controller 동작은 full-stack에서 검증하고, macOS/Metal static target의 MLX-VLM runtime은 native lifecycle과 static Gateway 경로에서 검증한다.

app-only 환경은 `.env.local.example`을 기반으로 생성하며 localhost endpoint를 사용한다.

---

### full-stack

full-stack은 Docker Compose를 사용해 application, model runtime, control plane, observability를 함께 실행한다.

```text
Client
  │
  ▼
Gateway
  │
  ├─ Main Model Runtime
  ├─ Embedding Runtimes
  ├─ Risk Signal Service ── Prompt Injection Detector Runtime
  └─ Runtime Controller ── Docker Engine

Observability
  ├─ Prometheus / Grafana
  ├─ DCGM / cAdvisor
  └─ Loki / Alloy
```

기본 실행 흐름은 다음과 같다.

```bash
HF_TOKEN=hf_xxx make up TARGET=linux-nvidia-dynamic ACCESS=local
make status
```

`make up`은 내부적으로 environment sync, 필요한 image/model cache 준비, Access Profile의 bind/auth projection,
Main Model boot projection과 Compose preflight를 수행한다. managed dynamic target은 strict readiness와 representative smoke까지 확인하고 static target은 외부 Main dependency를 포함한 Gateway readiness를 확인한다.
세부 Compose/readiness script는 maintainer 진단용 implementation이며 operator command가 아니다.

Main Model의 실제 실행 profile은 persisted runtime state와 boot policy를 반영해 결정된다.

---

## 4.2 Full-stack 실행 구조

full-stack의 base Compose 정의는 `ops/compose/full-stack.private-network.yaml`에 있다.

| Compose Service | Container Port | 역할 |
|---|---:|---|
| `gateway` | `9400` | 외부 API 진입점 |
| `runtime-controller` | `8080` | Main Model runtime control |
| `main-llm-vllm` | `9401` | Chat / Multimodal inference |
| `embedding-vllm` | `9402` | 범용 embedding |
| `prompt-injection-detector-runtime` | `9403` | Prompt risk inference |
| `risk-signal-service` | `9405` | Risk signal 처리 |
| `embedding-ko-vllm` | `9406` | Korean retrieval embedding |
| `prometheus` | `9090` | Metrics backend |
| `grafana` | `3000` | Dashboard |
| `dcgm-exporter` | `9400` | GPU metrics |
| `cadvisor` | `8080` | Container metrics |
| `loki` | `3100` | Log backend |
| `alloy` | - | Docker log 수집 |

위 표의 port는 **container 내부 port**다. Host에는 Gateway와 target이 제공하는 Grafana만 publish하며 실제 bind는 Access Profile이 결정한다.

application과 model runtime은 서로 다른 image 계층으로 실행된다.

```text
Platform Image
  ├─ gateway
  ├─ risk-signal-service
  └─ runtime-controller

vLLM Runtime Image
  ├─ main-llm-vllm
  ├─ embedding-vllm
  ├─ embedding-ko-vllm
  └─ prompt-injection-detector-runtime
```

각 model runtime은 독립 container와 port를 사용하며, GPU resource는 활성 runtime 사이에서 공유된다.

---

## 4.3 네트워크와 서비스 노출

Container 내부 통신과 Host 노출은 분리한다. 지원되는 full-stack host topology는
`private_network` 하나이며 Gateway와 Grafana만 host에 publish한다.

```text
Host Network
├─ Gateway
└─ Grafana

Compose Network
├─ main-llm-vllm
├─ embedding-vllm
├─ embedding-ko-vllm
├─ prompt-injection-detector-runtime
├─ risk-signal-service
├─ runtime-controller
├─ prometheus
├─ dcgm-exporter
├─ cadvisor
├─ loki
└─ alloy
```

모델 runtime, Risk Signal Service, Prometheus와 exporter/log backend는 host에 직접
publish하지 않는다. 제품·애플리케이션 요청은 Gateway를 통과하고, 내부 운영 연결은
Compose service DNS를 사용한다.

`make runtime-validate`도 같은 원칙을 따른다. validator는 실행 중인 Compose project에
one-off container로 참여하고 `configs/services.yaml`의 service name/container port로
내부 endpoint를 검사한다. 검증을 위해 host port를 추가로 열지 않으며
`--no-deps`로 실행해 dependency lifecycle도 변경하지 않는다.

```text
Host
  └─ make runtime-validate
          ↓
     one-off validator
          ↓ Compose network
     Gateway / vLLM / Risk / Prometheus / Grafana
```

현재 effective Compose 구성은 maintainer가 다음으로 확인한다.

```bash
bash scripts/compose/compose_config.sh
```

일반 사용자는 `make up ACCESS=local|private|edge`로 host bind와 인증 의도를 선택한다.
`local`과 `edge`는 loopback, `private`은 운영자가 선택한 LAN/VPN bind를 사용하지만,
어느 profile도 raw model/runtime/operations endpoint를 host에 공개하지 않는다.

기존 `EXPOSURE_MODE=master_open` 환경은 자동으로 다른 의미로 재해석하지 않는다.
`make up ACCESS=<profile>`으로 변경 계획을 확인한 뒤 `CONFIRM=access`로 명시적으로
지원 profile로 이관한다. 자세한 결정은
[ADR-0043](./adr/0043-internal-runtime-validation-and-private-host-exposure.md)을 따른다.


## 4.4 기동 순서와 Runtime 의존성

full-stack은 서비스 의존성과 공유 GPU 초기화 순서를 고려해 runtime을 기동한다.

대표적인 vLLM startup 순서는 다음과 같다.

```text
main-llm-vllm
      │ healthy
      ▼
embedding-vllm
      │ healthy
      ▼
embedding-ko-vllm
      │ healthy
      ▼
prompt-injection-detector-runtime
```

vLLM runtime은 초기화 과정에서 GPU memory를 확인하고 runtime memory를 구성한다. 순차 기동은 여러 runtime이 동일 GPU를 사용할 때 초기화 경쟁을 줄이는 역할을 한다.

Gateway는 기본적으로 `risk-signal-service`와 `main-llm-vllm`의 상태를 기준으로 기동되며, Runtime Controller는 Gateway의 hard startup dependency로 두지 않는다.

따라서 Runtime Controller 장애는 Main Model control에 영향을 주지만 Gateway process 자체의 기동과 직접 결합되지는 않는다.

Prometheus, Grafana, Loki, Alloy 등 observability 계층은 serving path와 독립적으로 운영된다.

---

## 4.5 Health와 Readiness

플랫폼은 process 생존 상태와 실제 serving 가능 상태를 구분한다.

```text
Process Start
    │
    ▼
/health
    │
    ▼
Dependency Ready
    │
    ▼
/ready
    │
    ▼
Inference / Smoke Validation
```

### `/health`

`/health`는 해당 process의 liveness를 확인한다.

Gateway `/health`가 성공해도 model runtime이나 다른 dependency의 준비 상태까지 보장하지는 않는다.

### `/ready`

Gateway `/ready`는 현재 요청 처리에 필요한 dependency 상태를 확인한다.

필수 dependency가 준비되지 않은 경우 HTTP `503`을 반환하며 응답에서 readiness 상태와 준비되지 않은 dependency를 확인할 수 있다.

```text
status: not_ready
phase: waiting_for_dependencies
not_ready_dependencies: [...]
required_not_ready_dependencies: [...]
optional_not_ready_dependencies: [...]
```

Runtime Startup Profile에서 stopped 또는 deferred로 지정된 non-main Model Runtime은 optional dependency로 처리될 수 있다.

### Operator readiness

정상 상태 확인은 backend 종류와 무관하게 `make status` 하나를 사용한다.

```bash
make status
```

`status`는 Gateway readiness와 현재 Runtime desired state/effective topology를 요약한다.
app-only에서는 application health를, full-stack에서는 현재 active/stopped/unavailable
Runtime 상태를 같은 표면에서 보여준다.

실제 serving path까지 포함한 strict validation은 별도 operator 명령이 아니라 `make up`의
완료 조건이다.

```text
make up
  ↓
Gateway /ready
  ↓
Dependency Ready
  ↓
Main Model Gate
  ↓
Representative Smoke
```

내부 `scripts/ops/ready_full.sh`와 `scripts/ops/smoke_test.sh`는 이 계약의 implementation
layer다. maintainer가 특정 계층만 분리 진단할 때 직접 실행할 수 있지만 일반 운영자가
별도 lifecycle 명령으로 기억하지 않는다.

Smoke는 Chat(Structured Output 포함)과 Risk 경로를 실제 요청으로 검증하고, non-main
Model Runtime은 `GET /admin/runtimes`의 현재 desired state와 effective topology를 기준으로
probe 대상을 결정한다. `active` Runtime의 inference 실패는 `make up` 실패이며,
의도적으로 `stopped`이거나 resource policy로 unavailable인 Runtime은 해당 Runtime 전용
probe를 보내지 않는다. `starting` 또는 현재 상태를 확정할 수 없는 Runtime은
fail-closed한다.

---

## 4.6 Runtime 운영 상태

### Main Model

Main Model은 profile 전환이 가능한 runtime이며 Gateway, Runtime Controller, vLLM Runtime이 역할을 나누어 관리한다.

```text
Gateway
  └─ Chat gate / in-flight request tracking

Runtime Controller
  └─ drain / container lifecycle / validation / rollback

Main Model vLLM
  └─ model load / inference
```

모델 전환 시 신규 Chat 요청을 제어하고, 기존 요청 drain과 runtime 재기동 및 검증을 거친다.

세부 switch API와 rollback 절차는 [6. 모델 운영](./06_model_operations.md)에서 설명한다.

### non-main Model Runtime

non-main Model Runtime은 Runtime Startup Profile에 따라 active 또는 deferred 상태로 운영할 수 있다.

reference Main resource policy에서 control 대상은 다음과 같다.

- `embedding`
- `embedding_ko`
- `prompt_injection_detector`

특정 Main resource policy와 공존할 수 없다고 검토된 runtime은 effective topology에서
control 대상에서 제외된다. 현재 `rtx4090-24gb`에서는 Prompt Injection Detector가 해당한다.

대표 profile은 다음과 같다.

| Runtime Startup Profile | 실행 상태 |
|---|---|
| `main_only` (기본) | Main Model 중심, non-main Model Runtime deferred |
| `retrieval_ready` | Main + embedding 계열 준비, Prompt Injection Detector deferred |

Runtime Startup Profile은 어떤 non-main runtime을 처음 active/deferred로 둘지만 결정한다.
Host publication은 별도 선택 profile이 아니라 고정 boundary다.

```text
Runtime Startup Profile
  └─ 어떤 runtime을 실행할 것인가

Host boundary
  ├─ Gateway
  └─ target이 monitoring stack을 제공하면 Grafana
```

모델 runtime, Risk Signal Service, Prometheus/exporter/log backend는 Compose 내부망에 유지된다.

---

## 4.7 공유 GPU 실행 모델

기본 runtime 구성에서는 여러 vLLM process가 하나의 NVIDIA GPU를 공유한다.

```text
NVIDIA GPU
├─ Main Model
├─ Embedding
├─ Embedding-KO
└─ Prompt Injection
```

각 runtime은 독립 process와 container로 실행되지만 GPU memory는 공용 resource다.

Runtime 시작과 Main Model 전환 시에는 현재 활성화된 runtime의 GPU budget을 함께 확인한다. Runtime Controller는 runtime activation 전에 GPU admission을 수행한다.

실제 VRAM budget, priority, eviction 정책은 [6. 모델 운영](./06_model_operations.md)과 `configs/gpu_budgets.yaml`에서 다룬다.

---

## 4.8 실행 모드 선택

작업 목적에 따라 실행 모드를 선택한다.

| 작업 | 권장 모드 | 주요 확인 |
|---|---|---|
| Gateway / Risk Signal Service 개발 | app-only | `make status` |
| API contract / validation 개발 | app-only | test + `make status` |
| 실제 Chat inference | full-stack | `make up` 완료 + `make status` |
| Embedding / Retrieval 검증 | full-stack | `make up` 완료 + Runtime 상태/API 검증 |
| Prompt Injection Detector Runtime 검증 | full-stack | `make up` 완료 + Runtime 상태/API 검증 |
| Main Model switch | full-stack | Model Operations 검증 |
| GPU budget 변경 | full-stack | Runtime / GPU validation |
| Compose / access 변경 | full-stack | `bash scripts/compose/compose_config.sh`, `make up ACCESS=<profile>` |
| NVIDIA runtime/container 관측 검증 | full-stack | Prometheus / Grafana / Loki 확인 |
| Metal 요청·runtime metric 관측 검증 | macOS Metal static | Prometheus / Grafana / Loki 확인 |

실행 환경과 관련된 주요 source of truth는 다음과 같다.

| 영역                      | 주요 파일                                         | 용도                                  |
| ----------------------- | --------------------------------------------- | ----------------------------------- |
| Base Compose topology   | `ops/compose/full-stack.private-network.yaml` | 전체 서비스의 기본 컨테이너 구성과 연결 관계 정의        |
| Service / port registry | `configs/services.yaml`                       | 서비스 이름, 포트, bind 정보 등 서비스 메타데이터 정의  |
| Host exposure boundary  | `configs/services.yaml` + target Compose `ports` | host-published service role과 실제 port projection |
| Runtime Startup Profile  | `configs/deploy_profiles.yaml`                | full-stack `make up` 시 초기 deferred runtime 조합 정의 |
| Effective Runtime topology | `configs/runtime_topology.yaml`             | feature/lifecycle binding과 Main resource-policy composition constraint 정의 |
| Model runtime           | `configs/model_serving.yaml`                  | 모델 runtime 연결, 제한값 및 serving 정책 정의  |
| Main Model profile      | `configs/main_model_profiles.yaml`            | Main Model별 runtime 및 실행 profile 정의 |
| GPU budget              | `configs/gpu_budgets.yaml`                    | GPU별 runtime 자원 사용 한도 정의            |
| Compose environment     | `.env.compose.example`                        | full-stack Compose 실행에 필요한 환경변수 예시  |
| Local environment       | `.env.local.example`                          | app-only 로컬 실행에 필요한 환경변수 예시         |


각 설정의 우선순위와 변경 반영 범위는 [5. 설정 체계와 Source of Truth](./05_configuration.md)에서 이어서 설명한다.

## Prompt Injection Detector resource-aware topology

`prompt_injection_detector`는 선언상 활성인 Model Runtime이며 reference Main resource policy에서는
Runtime Startup Profile과 Runtime Control 대상이다. 다만 `configs/runtime_topology.yaml`은
`unavailable_with_main_resource_variants`로 검토된 **runtime composition 제약**을 함께 선언한다.

현재 `rtx4090-24gb` Main resource-policy override에서는 Prompt Injection Detector가 effective
topology에서 비활성화된다. RTX 4090 실측에서 weight 1.42 GiB에 비KV overhead가 붙어 2.04 GiB가
바닥값이고, 8192 context의 KV 약 1.0 GiB까지 더해 약 3.05 GiB가 필요한 반면 Main Model과
embedding 두 종 상주 뒤 가용량이 그보다 작았기 때문이다.

이 제약은 RTX 4090이라는 GPU 제품명을 support allowlist로 쓰는 규칙이 아니다. Operator가
`MAIN_MODEL_RESOURCE_VARIANT=rtx4090-24gb`를 명시해 해당 Main resource policy를 선택했을 때만
적용된다. reference policy 또는 다른 검토된 policy에서는 detector가 다시 일반 controllable
runtime으로 동작한다.

effective topology는 Gateway 모델 목록과 readiness, Risk Signal Service detector registry,
Runtime Controller, `make up`의 startup profile, smoke/runtime validation에 공통으로 투영된다.
따라서 unavailable composition에서는 prompt 단독 endpoint가 `DETECTOR_DISABLED`이고 aggregate는
PII/Secret만 사용하지만 Risk feature 자체는 계속 제공된다.
