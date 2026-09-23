# 스크립트 안내

이 디렉터리는 운영자가 `make` 명령 뒤에서 실제로 호출하는 실행 스크립트를 모아 둔 곳이다. 설명은 한국어를 기본으로 쓰고, 파일명·환경 변수·API 경로·명령어는 원문을 유지한다.

> 어디서 시작할지 모르면 `docs/README.md`를 먼저 본다.

## 기본 흐름

정상 운영자는 내부 script를 조립하지 않는다.

```bash
make up TARGET=linux-nvidia-dynamic ACCESS=local  # 최초 1회
make status
make logs
make down
```

이후 재기동은 `make up`만 사용한다. project-local state 초기화는 `make reset`,
비싼 project-owned image/model cache와 volume까지 폐기할 때만 `make purge`를 사용한다.

이 디렉터리의 세부 script는 public command의 구현, 장애 evidence 수집, release/qualification,
변경 범위별 검증을 위해 존재한다. script가 존재한다는 이유만으로 operator command를
추가하지 않는다.

app-only 개발 흐름은 다음과 같다.

```bash
make setup-dev
make check
make init-env-local
make up
make status
make down
```

## 디렉터리 구조

| 디렉터리 | 역할 |
|---|---|
| `auth/` | auth profile plan/apply/status/doctor와 profile sanity check |
| `build/` | bootstrap, image build, package, Python/version checks |
| `compose/` | full-stack compose preflight, up, diagnostics, compose validation |
| `config/` | `.env` 생성 |
| `models/` | model registry CLI, vLLM command rendering, HF/unified image checks |
| `ops/` | start/stop/status/ready/smoke/reset/clean 같은 운영 명령 |
| `runtime/` | target 고유 native runtime 환경·모델·process lifecycle |
| `validation/` | contract validation, static validation, deterministic test runner, live runtime validation |
| `qualification/` | runtime-validation 결과와 현재 Main Model/runtime/GPU 관측으로 reviewable candidate 생성, reviewed plan/apply로 durable evidence 승격 |
| `validation/governance/` | 정적 계약 검증 체크 구현. 프로덕션 패키지(`src/`)가 아니라 여기 사는 이유는 서비스 실행에 필요 없고 런타임 이미지에 실릴 이유도 없기 때문이다. |
| `validation/runtime/` | live runtime 검증 체크 구현. 살아있는 스택을 밖에서 찔러보는 도구라 서비스 자신이 품지 않는다. |
| `lib/` | shell/python shared helpers |

## 주요 스크립트

| 파일 | 용도 |
|---|---|
| `platform_cli.py` | `up/status/down`의 target-aware operator lifecycle을 소유하고 setup/build/cache/readiness 세부 단계를 implementation script에 위임한다. |
| `build/setup_dev.py` | Platform `uv.lock`에서 개발용 `.venv`를 동기화한다. 기존 환경이 손상됐거나 Python minor가 다르면 자동 삭제하지 않는다. |
| `build/check_dev_environment.py` | Python 정책과 운영 shell helper에 필요한 Bash 4 이상을 진단한다. |
| `build/build_platform_image.sh` | Platform Dockerfile build·image import smoke 경로다. source revision/state와 target platform을 image label 및 로그에 남긴다. |
| `build/build_vllm_unified_image.sh` | Unified vLLM Docker build 경로다. `vllm_unified_build.yaml`의 target/base/pin을 사용하며 native Linux amd64 Docker daemon만 허용한다. |
| `config/setup_env.py` | `.env`를 생성·동기화하고 target이 소유한 Main profile·endpoint를 투영한다. 기존 인증·노출·image 값은 재생성하지 않는다. |
| `auth/auth_plan.py` / `auth/auth_apply.py` | secret을 출력하지 않고 auth profile 변경 계획을 보여주거나 managed auth flag만 적용한다. |
| `validation/validate_contracts.py` | OpenAPI refs, generated OpenAPI schema injection, JSON Schema, config, release hygiene 정책을 검증한다. |
| `validation/run_test.sh` | Python 버전과 test 환경을 고정하고 unit/contract test를 실행한다. |
| `lib/version_refs.py` | `VERSION` 문자열이 박혀 있는 모든 자리를 한 번만 선언한다. `build/reset_version.py`(생성)와 `validation/governance/versioning.py`(검증)가 같은 표를 읽으므로 두 목록이 갈라질 수 없다. |
| `lib/project_image_ownership.sh` | 로컬 build image의 ownership label과 legacy local repository 이름을 build/reset에 공통 제공한다. |
| `lib/gateway_runtime_state.sh` | `compose-up`이 Gateway에 초기 Runtime 지시를 전달하고 상태 디렉터리 소유권을 준비하는 규칙을 제공한다. `runtime-state.json` 자체는 쓰지 않는다. |
| `build/reset_version.py` | 프로젝트 버전을 `lib/version_refs.py`가 선언한 모든 자리에 한 번에 반영한다. 선언된 자리가 파일에서 사라졌으면 조용히 넘기지 않고 실패한다. |
| `build/check_python.py` | 현재 interpreter가 `>=3.12,<3.14`인지 fail-fast로 확인한다. |
| `ops/up_services.sh` | 로컬 app-only Gateway/Risk Signal Service를 실행하고 `/health`를 기다린다. |
| `ops/ready_local.sh` | app-only `/health` 상태를 strict하게 확인한다. app service가 내려가 있으면 실패하며 vLLM은 요구하지 않는다. |
| `ops/ready_full.sh` | strict `/ready`와 smoke test를 실행한다. 실제 vLLM runtime이 필요하다. |
| `compose/preflight_compose.sh` | full-stack compose 전 exposure config를 먼저 검증하고, 통과한 뒤 Docker, GPU 표시, effective compose host-published port, secret 상태를 점검한다. compose 내부 `expose` ports는 host port 검사 대상이 아니다. host bind와 port는 `docker compose config` 결과를 따른다. |
| `validation/runtime_validation.py` | 실제 runtime 검증 결과를 `reports/runtime/` 아래에 기록한다. |
| `qualification/produce_candidate.py` | 명시한 runtime-validation JSON과 현재 Admin Main Model 상태·NVIDIA GPU를 결합해 `reports/qualification/`에 reviewable receipt candidate를 만든다. repository evidence를 자동 수정하지 않는다. |
| `qualification/promote_candidate.py` | passed candidate만 durable receipt/catalog evidence로 승격한다. 기본 실행은 plan-only이며 candidate·catalog state를 묶은 plan digest를 exact confirm해야 apply한다. profile qualification status는 변경하지 않는다. |
| `models/check_hf_model_config.py` | 고정 vLLM runtime 환경에서 Transformers `AutoConfig`만 로드해 engine·GPU 이전 config loader 문제를 분리한다. |
| `build/package_release.sh` | 배포 ZIP을 만들고 secret, log, cache, egg-info, generated runtime report를 제외한다. ZIP root는 항상 `ai_model_serving_platform/`로 고정한다. |
| `ops/down_all.sh` | `.env`와 Compose project name에 의존하지 않고 이 checkout의 host process와 Compose container/network를 정지한다. |
| `ops/clean_project.sh` | build/test 산출물과 runtime report를 정리한다. 실행 중인 host process가 있으면 중단하며 `--dry-run`, `--logs`만 지원한다. |
| `ops/reset_all.sh` | 기본 실행은 project-local 초기화 plan만 출력하고, 정확한 확인값에서 해당 state만 삭제한다. Docker build cache와 전역 model cache는 보존한다. |
| `build/reset_version.py` | VERSION, OpenAPI, pyproject, env 예시, platform image tag를 같은 버전으로 맞춘다. |

## 운영 주의사항

- app-only `.env`의 `make up`은 vLLM을 시작하지 않고 Gateway/Risk Signal Service만 실행한다.
- full-stack `make up`은 Docker/GPU/port/secret preflight와 strict readiness/smoke를 내부적으로 수행한다.
- 기본 Runtime Startup Profile은 `main_only`다. Retrieval runtime도 처음부터 필요하면
  `RUNTIME_STARTUP_PROFILE=retrieval_ready make up`을 사용한다.
- `.runtime/prometheus/admin_api_key`가 사라져도 `.env`를 다시 만들지 않는다. 다음
  `make up`이 runtime secret을 복구한다.
- live qualification용 상세 runtime 검증은 developer/maintainer command
  `make runtime-validate`가 소유하며 정상 기동 확인을 위해 별도로 실행하지 않는다.
- 저비용 repository build/test artifact만 직접 정리해야 하는 maintainer 작업은
  `scripts/ops/clean_project.sh --dry-run`으로 범위를 확인한다. 일반 사용자는
  `reset` 또는 `purge`의 명확한 파괴 범위를 사용한다.
- `.runtime/`은 정상 local runtime state이며 release/source package에 포함되지 않는다.

## Full-stack 진단

- `validate_vllm_compose.py`: compose vLLM command와 model serving/catalog/card 정책 정합성을 검증한다. Embedding pooling token budget 오류와 risk detector quantization drift를 사전에 막는다.
- `compose_diagnostics.sh`: `make up`의 strict readiness 실패 시 service별 raw evidence를 `.runtime/diagnostics/`에 저장하고 terminal에는 알려진 원인과 비정상 service만 요약한다.
- `check_hf_model_config.py`: weight load 이전 HF config 문제를 분리하는 내부 helper다. 호스트 Platform 환경에 Transformers를 중복 설치하지 않고 `check_risk_vllm_image_config.sh`가 고정 vLLM image 안에서 실행한다.
- `prepare_main_model_cache.py`: allowlisted main-model profile의 고정 revision 전체 snapshot을 공용 HF cache에 준비하고 local-only로 재검증한다. `make main-model-prepare PROFILE=<id>`로 실행하며 active runtime은 변경하지 않는다.
- `render_main_model_boot_override.py`: locked/configured/persisted profile 우선순위를 검증해 일회성 Compose boot projection을 원자적으로 생성한다. 공식 로컬·CI 실행 경로는 임시 파일을 사용하고 종료 시 삭제한다.

Risk detector의 `bitsandbytes` 설정은 운영 기본값이다. 원인 분리를 위한 A/B 테스트는 별도 override에서 수행하고, 기본 compose에서 임의 제거하지 않는다.

## Unified vLLM 이미지와 Kanana patch 점검

- 정상 target 기동은 `make up`이 필요한 local Platform/Unified image를 Docker cache를
  사용해 수렴시킨다.
- Unified vLLM image 자체를 개발·qualification 목적으로 직접 빌드할 때는
  `make build-vllm-unified-image`를 사용한다.
- cache 없이 재현해야 하는 maintainer 검증은
  `PROJECT_BUILD_NO_CACHE=1 bash scripts/build/build_vllm_unified_image.sh`처럼
  implementation layer에서 명시적으로 수행한다.
- full-stack preflight는 active image의 label, metadata와 model config load를 검증한다.
  해당 검사 우회는 production promotion 계약이 아니다.

## 인증 제어 플레인 점검

`make auth-status`로 현재 public/admin/internal auth 상태를 확인하고, `make auth-doctor`로 위험 조합을 탐지한다. 후보 env 파일은 `make auth-status ENV=<path>`와 `make auth-doctor ENV=<path>`로 root `.env` 반영 전에 점검한다. 변경 전에는 `make auth-plan MODE=strict ENV=<path>`로 plan을 보고, 적용은 `make auth-apply MODE=strict ENV=<path>`로 managed auth flag만 수정한다. secret 값은 출력하지 않는다.

## Risk vLLM patch 생명주기

`build_vllm_unified_image.sh`는 `ops/patches/` 아래 patch script를 포함한 unified 이미지를 빌드한다. `check_risk_vllm_image_config.sh`는 그 안의 Kanana patch label, metadata, config loading을 검증한다.

## OpenAPI projection 검증

`scripts/openai_compatibility.py`는 `specs/schemas/chat_completion_*.schema.json`의 `x-openai-compatibility` 선언에서 `docs/reference/openai_compatibility.md`를 생성한다. 분류가 없는 파라미터가 있으면 문서를 만들지 않고 실패한다 -- 기본값으로 "표준"을 넣으면 새 확장이 OpenAI 표준인 것처럼 실리기 때문이다.

정적 OpenAPI(`specs/openapi.*.yaml`)는 `make render-runtime-assets`로 생성하고, `make validate`의 `generated artifacts` 단계에서 `render_runtime_assets.py --check`가 생성 문서 전체와 구조 비교한다. 계약 스키마 본문은 `specs/schemas/*.json`이 단일 소유자이며 생성 문서에도 그 파일에서 주입되므로 별도 대조 단계를 두지 않는다.
