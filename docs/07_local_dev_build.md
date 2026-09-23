# 7. 로컬 개발과 빌드

AI Model Serving Platform은 **operator lifecycle**과 **developer/maintainer tooling**을
분리한다. 일반 사용자는 build, model download, Compose readiness 단계를 직접 조립하지
않는다.

```bash
# 최초 1회
HF_TOKEN=hf_xxx make up TARGET=linux-nvidia-dynamic ACCESS=local

# 이후
make up
make status
make logs
make down
```

`make up`은 필요한 runtime Python environment, target configuration, project-owned image,
Main Model cache, runtime startup와 strict readiness/smoke를 현재 상태에 맞춰 수렴한다.
이미 현재 source와 맞는 image와 pinned model snapshot은 재사용한다.

개발자는 코드 변경 검증을 위해 `make app-check` 또는 `make check`를 사용한다.
개별 image build, runtime validation, package 생성과 implementation script는 변경 범위를
검증하기 위한 developer/maintainer surface이며 정상 operator lifecycle을 확장하지 않는다.

명령 책임과 파괴 범위는 [ADR-0039](adr/0039-operator-intent-lifecycle-and-diagnostics.md)을
따른다. Runtime 구조와 실행 모드는 [4. 실행 환경과 모드](./04_runtime_modes.md), 설정 파일과
환경변수는 [5. 설정 체계와 Source of Truth](./05_configuration.md), 상세 테스트 구성은
[8. 테스트와 검증](./08_testing_validation.md)에서 설명한다.

---

## 7.1 개발 환경 확인

개발 작업에 필요한 환경은 작업 범위에 따라 달라진다.

| 작업 | 주요 요구사항 |
|---|---|
| Application 개발·검증·테스트 | Python `>=3.12,<3.14`, `pyproject.toml`에 고정된 uv |
| Control Plane 검증 | `ui/control-plane/package.json`에 고정된 Node.js / npm |
| Platform Image Build | Docker CLI / Docker daemon. 로컬 기본 target은 daemon architecture |
| Full-stack 실행 | Bash 4 이상, native Linux amd64 Docker daemon, NVIDIA GPU/driver/Container Toolkit |
| Unified vLLM Image Build | `vllm_unified_build.yaml` target과 같은 native Docker daemon. CUDA/NVIDIA image 전용 |
| Model 다운로드 | Hugging Face token 및 모델별 사용 조건 |

프로젝트가 지원하는 Python 범위는 `pyproject.toml`의 `requires-python`을 기준으로 하며, 현재 CPython 3.12와 3.13을 지원한다. 오래되거나 아직 채택하지 않은 Python에서도 먼저 오류를 안내할 수 있도록 bootstrap guard에도 같은 범위가 있고, `make validate`가 두 값의 일치를 확인한다.

Linux Platform image의 기준은 Dockerfile에 고정된 Python 3.12 patch와 base image digest다.
`.python-version`은 로컬 application 개발 기본값인 Python 3.13 patch를 가리키며 native
MLX runtime도 별도 설정에서 Python 3.13을 사용한다.
이는 개발용/운영용 등급 구분이 아니라 실행 backend의 호환 경계다. Platform 코드는 하나의
`pyproject.toml`과 `uv.lock`으로 두 minor를 함께 지원하고, MLX만 충돌하는 native dependency
때문에 `runtimes/mlx/`의 독립 project와 lock을 사용한다.

로컬 Make 명령은 프로젝트의 `.venv`가 존재하면 해당 Python을 우선 사용한다. 호출자가 `PYTHON_BIN`을 지정한 경우에는 지정된 interpreter를 사용한다.

### 개발 환경 준비

애플리케이션 환경 준비와 정적 검증·테스트에는 Bash 4를 강제하지 않는다.

Python 3.12 또는 3.13과 uv를 준비한 뒤 OS와 관계없이 같은 명령을 사용한다.
uv가 없다면 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에서
`pyproject.toml`의 `tool.uv.required-version`에 고정된 버전을 설치한다.

```bash
make setup-dev
make app-check
```

`make app-check`는 Python application/config/contracts만 검증한다. Control Plane까지 포함한 저장소 전체
변경은 `make check`를 사용하며, 이 경우 `ui/control-plane/package.json`의 `engines`와
`packageManager`에 고정된 Node.js/npm toolchain이 추가로 필요하다. `make check`는 내부적으로
`make app-check`와 `make console-check`를 순서대로 호출한다.

로컬 개발은 Python 3.13을 권장한다. 별도로 설치한 Python을 쓰려면
`make setup-dev PYTHON_BIN=/path/to/python3.13`으로 지정한다. uv는 기존 `.venv`가 없으면
이를 만들고, 있으면 같은 minor인지 확인한 뒤 lock과 정확히 동기화한다. 저장소 wrapper는
손상되었거나 다른 minor인 기존 환경을 임의 삭제하지 않는다.

환경 파일 helper와 일부 Compose·배포 스크립트는 associative array나 `mapfile`을 사용하므로 Bash 4 이상이 필요하다. macOS에서 해당 운영 명령까지 실행하려면 `brew install bash` 후 Homebrew Bash를 PATH에 추가한다. `make doctor-dev`는 실제 Python 경로와 Bash 버전, 기준 Python 버전을 함께 확인하는 운영 도구 진단이다. 기본 로그인 shell(zsh)을 바꿀 필요는 없다.

`setup-dev`는 Platform `uv.lock`을 `--locked`로 설치하고 quality dependency group을 포함한다.
의존성 해석·가상환경 생성·불필요 package 제거는 uv가 소유하며 저장소가 이를 재구현하지 않는다.

이 명령은 `.env`와 runtime state를 생성·변경하지 않는다. macOS app/contract 검증 통과가 `macos-metal-static` 모델 runtime의 qualification을 의미하지는 않는다([ADR-0020](adr/0020-runtime-control-and-deployment-targets.md)).

빌드 재현성의 범위도 실행 환경별로 구분한다.

| 경로 | 고정되는 입력 | 결과의 의미 |
|---|---|---|
| 로컬 `make build-image` | Dockerfile base digest, Platform `uv.lock`, 현재 working tree | 변경 중인 코드를 확인하는 로컬 image ID |
| GitHub Actions | Platform `uv.lock`과 Python minor | macOS/Ubuntu app·contract 검증. image artifact 없음 |
| Linux Platform 운영 후보 | clean commit, Linux amd64 target, base digest, Platform `uv.lock` | publish 전 로컬 image; 승격 시 registry digest 필요 |
| Linux Unified vLLM 운영 후보 | clean commit, native Linux amd64, vLLM base digest와 compatibility pin | publish 전 NVIDIA runtime image; 승격 시 registry digest 필요 |

같은 Dockerfile과 build script를 공유하는 것은 입력 해석을 맞추기 위한 것이다. 로컬의
수정된 working tree나 arm64 image ID가 clean Linux amd64 운영 후보와 byte-identical하다는
뜻은 아니다. Registry publish 자동화는 현재 정의하지 않으며, publish 결과의 immutable
registry digest는 외부 artifact identity로 사용할 수 있다. 해당 digest를 실제 host에서
사용하려면 persistent image pin을 명시적으로 갱신한 뒤 canonical lifecycle로 수렴시킨다.

### Dependency lock 갱신

Platform은 root `pyproject.toml`, MLX native runtime은 `runtimes/mlx/pyproject.toml`이
각자의 direct dependency Source of Truth다. 같은 위치의 `uv.lock`은 Linux/macOS와
지원 architecture 조건을 포함한 해석 결과다.

```bash
make lock
```

`make lock`은 각 project의 `requires-python`과 root `.python-version`을 따라 두 lock을
현재 pin을 유지하는 방식으로 다시 해석한다. 현재 활성 `.venv`의 Python을 두 project에
강제로 재사용하지 않는다. 전체 upgrade는 이 명령의 암묵적 동작이 아니며 별도 변경으로
수행한다. Lock 형식과 dependency graph의 정합성은 uv가 소유하므로 별도 custom parser나
OS별 requirements 복사본을 두지 않는다.
`make setup-dev`, MLX setup, Platform image build가 각각 `--locked`로 소비하면서 stale lock을
실제 경계에서 거부한다.

Full-stack 환경에서는 NVIDIA GPU와 NVIDIA Container Toolkit을 통해 vLLM container가 GPU에 접근한다. Hugging Face에서 모델을 가져오는 runtime은 `.env`의 `HF_TOKEN` 또는 `HUGGING_FACE_HUB_TOKEN`을 사용한다.

환경 파일의 생성과 관리 방식은 [5.10 환경 파일](./05_configuration.md#510-환경-파일)을 참고한다.

---

## 7.2 기본 개발 흐름

일반적인 source 변경은 다음 순서로 확인한다.

```bash
make app-check
```

`app-check`의 내부 단계는 `make validate`와 `make test`이며, 세부 실패를 분리해 확인할 때 두 명령을
직접 실행할 수 있다. 검증이 완료되면 변경 범위에 맞는 실행 환경을 선택한다.

| 변경 범위 | 권장 확인 환경 |
|---|---|
| Gateway routing / validation | app-only |
| Authentication / error handling | app-only |
| Risk Signal Service application logic | app-only |
| Main Model inference | full-stack |
| Embedding / Retrieval runtime | full-stack |
| Prompt Injection vLLM | full-stack |
| GPU / Runtime lifecycle | full-stack |
| Dockerfile / application dependency | Platform Image Build |
| vLLM base / compatibility pin / runtime patch | Unified vLLM Image Build |

### Application 변경

```text
Source 변경
   ↓
make check
   ↓
make up
   ↓
make status
```

### Runtime 통합 변경

```text
Source / Config 변경
   ↓
make check
   ↓
make up
   ↓
필요한 image/cache만 자동 수렴
   ↓
strict readiness + representative smoke
```

`make validate`와 `make test`가 검사하는 세부 항목은 [8. 테스트와 검증](./08_testing_validation.md)에서 다룬다.

---

## 7.3 app-only 실행

app-only는 Gateway와 Risk Signal Service를 로컬 Python process로 실행하는 개발 방식이다.

### 환경 준비

```bash
make init-env-local
```

`make init-env-local`은 `.env.local.example`을 기준으로 app-only용 `.env`를 준비한다.

### 서비스 실행

```bash
make up
```

app-only `.env`에서 `make up`은 다음 application process를 실행한다.

```text
Developer Host
│
├─ Gateway       localhost:9400
└─ Risk Signal Service  localhost:9405
```

각 process를 시작한 뒤 `/health` 응답을 확인하고 실행 결과를 `run/`과 `logs/`에 기록한다.

### 상태 확인

```bash
make status
```

app-only에서 `make status`는 Gateway와 Risk Signal Service의 application health를 확인한다.

app-only는 다음과 같은 application layer 작업에 적합하다.

- API routing
- request validation
- authentication
- error mapping
- OpenAPI / schema 변경
- Gateway와 Risk Signal Service 로직

### 종료

```bash
make down
```

app-only와 full-stack의 구조적 차이는 [4.1 실행 모드](./04_runtime_modes.md#41-실행-모드)를 참고한다.

---

## 7.4 full-stack 실행

full-stack은 Docker Compose를 사용해 application, model runtime, control plane, observability를 함께 실행한다.

### 환경 준비와 기동

새로운 full-stack 개발 환경은 첫 `make up`에서 target을 한 번 선택한다. `.env`가 없으면
target 기본 profile과 endpoint를 생성하고, 필요한 image와 Main Model snapshot만 준비한다.

```bash
HF_TOKEN=hf_xxx make up TARGET=linux-nvidia-dynamic ACCESS=local
```

일반 재기동은 `make up` 하나다. local image가 현재 clean source와 일치하고 pinned model
snapshot이 이미 cache에 있으면 재사용한다.

Compose용 `.env`만 직접 생성해야 하는 유지보수 상황에서는 다음 내부 명령을 사용한다.

```bash
make init-env-compose
```

Hugging Face에서 모델을 가져오는 runtime은 `.env`에 설정된 token을 사용한다.

### Stack 실행

```bash
make up
```

기본 `main_only` profile은 Main Model만 준비하고 non-main Model Runtime은 stopped 상태로
생성한다. Retrieval runtime도 처음부터 필요하면
`RUNTIME_STARTUP_PROFILE=retrieval_ready make up`을 명시한다.

내부적으로 `scripts/compose/compose_up.sh`는 다음 준비 작업을 수행한 뒤 effective Compose stack을 기동한다.

1. `.env` contract 검증
2. runtime secret 준비
3. Exposure Profile 적용
4. persisted Main Model profile을 반영한 boot projection 생성
5. 같은 boot projection으로 effective Compose config와 preflight 검증
6. 선택된 Main Model의 Hugging Face cache 준비
7. 서비스 기동

Preflight와 기동은 같은 `base → exposure override → boot override` 순서를 사용한다. `scripts/compose/compose_up.sh`에서 생성한 boot 파일을 `--boot-override`로 전달하므로 preflight 중 persisted state를 다시 읽어 다른 프로필을 고르지 않는다. Preflight를 단독 실행하면 기존 boot resolver로 임시 override를 만들고 종료 시 삭제한다.

정상 preflight 뒤에는 같은 `docker compose config` 검사를 반복하지 않는다. 기존 정책에 따라 명시적으로 preflight를 생략한 경우에만 별도 config 검사를 실행한다.

메인의 effective image·command는 이 boot projection과 비교하며, GPU 예산 합계에도 실제 command의 host override를 반영한다. 보조 모델 command와 Sidecar admission은 계속 `model_serving.yaml`의 같은 고정 예산을 기준으로 검사한다. 보조 모델에 별도 host override 계약은 두지 않는다.

실제 host port 공개 범위는 `EXPOSURE_MODE`에 따라 결정된다. 자세한 내용은 [4.3 네트워크와 서비스 노출](./04_runtime_modes.md#43-네트워크와-서비스-노출)을 참고한다.

### 준비 상태 확인

```bash
make status
```

`make up`은 Gateway와 vLLM dependency readiness 및 실제 inference path까지 확인한 뒤
성공한다. 이후 `make status`는 현재 상태를 짧게 확인한다. 특정 readiness implementation만
분리해 디버깅해야 하는 maintainer는 `bash scripts/ops/ready_full.sh`를 직접 실행한다.

Full-stack은 다음 작업에 사용한다.

- Main Model inference
- Embedding / Retrieval
- Prompt Injection Detector Runtime
- Main Model switching
- GPU resource admission
- Docker runtime lifecycle
- Observability 연동

### Stack 종료

```bash
make down
```

---

## 7.5 Platform Image Build

Platform Image는 Gateway, Risk Signal Service, Runtime Controller 등 application과 control-plane 코드를 실행하는 Docker image다.

기본 image tag는 프로젝트 `VERSION`을 사용한다.

```text
ai-model-serving-platform:<VERSION>
```

### Operator lifecycle의 image convergence

일반 운영자는 target image를 별도 명령으로 먼저 만들지 않는다. `make up`이 external
registry digest는 보존하고, project-owned local image는 현재 source와의 일치 여부를
확인해 필요한 경우 Docker cache를 사용해 다시 만든다.

특정 image 자체를 개발·CI 목적으로 검증하는 명령은 아래 developer build surface가 소유한다.

### Image만 Build

```bash
make build-image
```

`make build-image`는 `Dockerfile`을 사용해 Platform Image를 생성하고, 생성된 image 안에서 Gateway와 Risk Signal Service application factory를 실제로 import·초기화한다.

| 명령 | 범위 |
|---|---|
| `make up` | 정상 lifecycle에서 필요한 project-owned image만 수렴 |
| `make build-image` | Platform Image Build + image 내부 application 확인 |
| `make build-vllm-unified-image` | Unified vLLM Image 직접 Build |

`PLATFORM_IMAGE` 환경변수로 build tag를 지정할 수 있으며, 기본값은 `ai-model-serving-platform:<VERSION>`이다.

이 값은 호출 process의 명시적 build override이며 runtime `.env`를 암묵적으로 읽지
않는다. Runtime image 선택과 build output tag를 분리해 `.env`의 운영 설정이나
credential이 Docker build process에 불필요하게 로드되지 않게 한다.

로컬 기본 build target은 Docker daemon의 architecture다. 예를 들어 Apple Silicon의
Docker Desktop에서는 일반적으로 Linux arm64 image가 생성된다. 운영 target과 같은
architecture의 application image가 필요한 경우 다음처럼 명시할 수 있다.

```bash
PLATFORM_BUILD_PLATFORM=linux/amd64 make build-image
```

Build 로그와 image label에는 Git revision, working tree의 clean/dirty 상태와 target
platform이 남는다. dirty 상태는 개발 중 image로 허용하지만 clean-commit release artifact로
오인하지 않도록 경고한다. 로컬 tag는 mutable하므로 배포 입력으로 사용하지 않는다.

Platform Image build는 `scripts/build/build_platform_image.sh`, Unified vLLM Image build는
`scripts/build/build_vllm_unified_image.sh`가 소유한다. 현재 GitHub Actions는 image를
빌드하거나 publish하지 않는다. 향후 자동화도 이 스크립트를 호출하고 registry push와
digest 전달만 외부 adapter에서 담당한다. 자동화 경계는 [9. 자동화 경계](./09_cicd.md)에서
설명한다.

---

## 7.6 Unified vLLM Image Build

Main Model, Embedding, Korean Embedding, Prompt Injection Detector Runtime은 하나의 **Unified vLLM Image**를 공유한다.

```text
Unified vLLM Image
├─ Main Model
├─ Embedding
├─ Korean Embedding
└─ Prompt Injection
```

기본 build 명령은 다음과 같다.

```bash
make build-vllm-unified-image
```

이 명령은 CUDA 기반 운영 image를 만드는 경로다. Host OS 이름을 판정하지 않고
`configs/vllm_unified_build.yaml`의 `target_platform`과 Docker daemon platform이
일치하는지 확인한다. 현재 target은 `linux/amd64`이며 emulation build는 지원 범위에
넣지 않는다. M5 Metal은 CUDA image의 cross-build가 아니라 별도 runtime 환경과 모델
qualification으로 진행한다.

Unified vLLM Image의 주요 build 입력은 다음과 같다.

| 입력 | 역할 |
|---|---|
| `ops/images/vllm-unified/Dockerfile` | Derived runtime image 구성 |
| `configs/vllm_unified_build.yaml` | Target platform, base image와 compatibility pin 관리 |
| `ops/images/vllm-unified/requirements.media.lock` | 고정 vLLM base에서 검증하는 multimodal media overlay |
| `ops/patches/apply_gemma4_multimodal_patches.py` | Gemma4 multimodal compatibility patch |
| `ops/patches/apply_gemma4_streaming_reasoning_patch.py` | Gemma4 streaming reasoning/content parser compatibility patch |
| `ops/patches/transformers_llama_head_dim_guard.py` | Prompt Injection Llama `head_dim` compatibility patch |
| `scripts/build/build_vllm_unified_image.sh` | Native target 확인과 Docker build argument 조립 |
| `scripts/models/print_vllm_unified_compatibility.py` | build config의 target/dependency pin projection |

Build script는 `print_vllm_unified_compatibility.py`를 통해 `configs/vllm_unified_build.yaml`의
target platform과 compatibility version을 읽어 Docker build argument로 전달한다.

Unified vLLM Image는 다음 변경에서 다시 빌드한다.

- vLLM base image 변경
- Transformers / Hugging Face compatibility pin 변경
- media dependency 변경
- runtime patch 변경
- Unified vLLM Dockerfile 변경

일반 application source 변경은 Platform Image build 흐름에서 확인한다.

Unified vLLM build 입력이 바뀌면 운영자가 새 image를 명시적으로 빌드한다. 자동 감지와
registry publish는 현재 구성하지 않으며, 향후 자동화 원칙은 [9. 자동화 경계](./09_cicd.md)에서 설명한다.

`make up`의 artifact convergence는 로컬에서 빌드한 Unified image tag를 Docker의 content-addressed
`sha256:...` image ID로 해석하고, `.env`에서 그 build tag와 정확히 일치하는 unified
image 값만 고정한다. 운영자가 별도로 지정한 image ref는 추측해서 덮어쓰지 않는다.
다른 host나 외부 automation에서 같은 artifact를 사용하려면 publish된 registry의
`name@sha256:...` digest를 persistent image pin으로 사용한다.

### 반복 개발과 재빌드

앱 코드만 바뀌었다면 developer command `make build-image`로 Platform image만 확인할 수
있다. Unified runtime patch나 base 입력을 cache 없이 재현해야 하는 maintainer 검증은
implementation script에 `PROJECT_BUILD_NO_CACHE=1`을 명시한다.

```bash
PROJECT_BUILD_NO_CACHE=1 bash scripts/build/build_vllm_unified_image.sh
```

정상 operator lifecycle에서는 `make up`이 필요한 image와 model cache를 수렴하므로 별도의
build/prepare 순서를 요구하지 않는다.

---

## 7.7 Release Package

배포용 source artifact는 ZIP package로 생성한다.

```bash
make package
```

기본 출력은 다음과 같다.

```text
dist/ai_model_serving_platform_<VERSION>.zip
```

Release package에는 Git이 추적하는 파일 중 실행에 필요한 source, config, spec, ops
artifact, 테스트와 `env_contract.yaml`에 선언된 안전한 `.env.*.example` 파일이
포함된다. GitHub Actions workflow는 배포 artifact에 포함하지 않는다.

Packaging 과정에서는 다음 항목을 배포 artifact에서 분리한다.

- `.venv/`
- local log / run data
- model cache
- runtime-generated state와 report
- 실제 `.env`
- private key / secret file
- local tool / private workspace directory

ZIP entry의 timestamp는 고정값을 사용해 동일한 source에서 재생 가능한 package 형태를 유지한다.
패키지 입력은 현재 working tree의 Git tracked 파일로 한정해, 로컬의 untracked
메모나 임시 파일이 같은 commit의 ZIP에 섞이지 않게 한다.

`make package`는 package 생성 전에 별도 축약 검증을 만들지 않고 `make validate`와 같은 전체 정적 gate를 수행한다. 생성된 ZIP은 제외 대상 파일과 환경 파일이 포함되지 않았는지 다시 검사한다.

Release ZIP은 배포에 필요한 artifact와 `tests/`를 함께 담는다. CI와 배포 전 `make check`가
같은 source의 테스트를 실행할 수 있어야 한다. 테스트 구조와 release gate의 관계는
[8. 테스트와 검증](./08_testing_validation.md), 실제 배포 절차는 [10. 배포](./10_deployment.md)에서 설명한다.

---

## 7.8 종료·초기화·폐기

일반 종료는 checkout이 소유한 실행 리소스를 정지하고 image, model cache와 persistent
configuration을 보존한다. `.env`가 일부 손상되거나 없어도 checkout ownership label/PID
기반 fallback을 같은 `make down`이 소유한다.

```bash
make down
```

local configuration/runtime state를 처음부터 다시 만들고 싶을 때는 `reset`을 사용한다.
기본 실행은 plan-only다.

```bash
make reset
make reset CONFIRM=reset
```

`reset`은 `.env`, `.venv`, `.runtime`, process log/run file과 저비용 build/test
artifact를 제거하지만 project-built image와 repository-local model cache, Docker volume은
보존한다.

비싼 재사용 artifact까지 버려 디스크를 회수하려면 `purge`를 사용한다.

```bash
make purge SCOPE=cache
make purge SCOPE=cache CONFIRM=purge

make purge SCOPE=all
make purge SCOPE=all CONFIRM=purge
```

`cache` scope는 project-owned image, repository-local model cache, identifiable project
Compose volume과 diagnostic/build artifact를 제거하고 configuration state는 보존한다.
`all`은 여기에 reset 범위를 추가한다.

어느 scope도 global Hugging Face cache, daemon-wide BuildKit cache, 다른 checkout/image/volume을
삭제하지 않는다. daemon 전체 prune은 repository lifecycle에 포함하지 않는다.

저비용 repository artifact만 maintainer가 직접 정리해야 하는 경우
`bash scripts/ops/clean_project.sh --dry-run`으로 implementation 범위를 먼저 확인한다.

---

## 7.9 결과 확인

| 작업 | 확인 명령 | 확인 범위 |
|---|---|---|
| app-only/full-stack 현재 상태 | `make status` | Gateway readiness와 현재 Runtime policy state |
| 정상 lifecycle convergence | `make up` | 필요한 artifact 준비 + startup + strict readiness/smoke |
| Platform Image 직접 검증 | `make build-image` | Docker build + application import |
| Unified vLLM Image 직접 검증 | `make build-vllm-unified-image` | CUDA runtime image build |
| 서비스/Runtime raw log | `make logs SERVICE=<id>` | 선택 service의 bounded raw evidence |
| Release ZIP | `make package` | package validation + ZIP 생성 |

Compose effective config만 확인하는 maintainer 작업은
`bash scripts/compose/compose_config.sh`를 사용한다. 일반 운영에서는 `make up` preflight가
같은 effective configuration을 검증한다.

---

## 7.10 작업별 빠른 참조

| 목적 | 명령 |
|---|---|
| 최초 target 선택 + 전체 시작 | `make up TARGET=<id> [ACCESS=local|private|edge]` |
| 이후 전체 시작/수렴 | `make up` |
| 통합 상태 | `make status` |
| 운영 event / log | `make logs` |
| 전체 종료 | `make down` |
| local state 초기화 | `make reset` |
| project cache/artifact 폐기 | `make purge SCOPE=cache|all` |
| application 변경 검증 | `make app-check` |
| repository 전체 검증 | `make check` |

개별 image build, readiness, smoke, Compose/Metal lifecycle script는 operator command가 아니라
developer/maintainer implementation surface다.

---

## 7.11 관련 문서와 Source of Truth

| 영역 | 문서 / 파일 | 역할 |
|---|---|---|
| Runtime 실행 구조 | [4. 실행 환경과 모드](./04_runtime_modes.md) | app-only / full-stack, network, readiness |
| 설정 관리 | [5. 설정 체계와 Source of Truth](./05_configuration.md) | 환경변수, image, runtime 설정 |
| 모델 운영 | [6. 모델 운영](./06_model_operations.md) | Main Model start / stop / switch |
| 테스트 | [8. 테스트와 검증](./08_testing_validation.md) | validate, test, runtime validation |
| 자동화 경계 | [9. 자동화 경계](./09_cicd.md) | 현재 자동 검증과 미래 publish·deploy 연결 원칙 |
| 배포 | [10. 배포](./10_deployment.md) | target lifecycle, image pin과 component rollback |
| Make entry point | `Makefile` | 로컬 개발·빌드 명령 |
| Platform image | `Dockerfile` | application / control-plane image |
| Platform build script | `scripts/build/build_platform_image.sh` | Provider-neutral Platform build |
| Unified vLLM build config | `configs/vllm_unified_build.yaml` | target platform, base image와 compatibility pin |
| Unified vLLM Dockerfile | `ops/images/vllm-unified/Dockerfile` | derived vLLM runtime image |
| Target lifecycle | `scripts/platform_cli.py` | setup/build/prepare/up/status/down 조합 |
| Checkout 전체 종료 | `scripts/ops/down_all.sh` | `.env` 독립적인 project-owned runtime 회수 |
| 프로젝트 로컬 상태 초기화 | `scripts/ops/reset_all.sh` | 확인 기반 project-local state 삭제 |
| Release package | `scripts/build/package_release.sh` | 배포용 ZIP 생성 |
