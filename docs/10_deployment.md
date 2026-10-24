# 10. 배포

이 프로젝트에서 배포는 별도의 원격 release state machine이 아니라 **선택한 host에서
target-aware local lifecycle을 실행해 선언된 구성과 실제 Runtime을 수렴시키는 과정**이다.

```text
Repository / Published Images
          ↓
make up TARGET=<deployment-target>
          ↓
configuration / image / model cache convergence
          ↓
runtime startup + target readiness
          ↓
make status
          ↓
optional post-start qualification: make smoke
          ↓
Control Plane operations
```

자동화와 artifact 생성의 책임 경계는 [9. 자동화 경계](./09_cicd.md), Runtime 구조는
[4. 실행 환경과 모드](./04_runtime_modes.md), 설정 Source of Truth는
[5. 설정 체계와 Source of Truth](./05_configuration.md)를 참고한다.

---


### 이전 관리형 Target을 공통 Runtime Controller로 전환

`linux-cpu-managed` 및 `linux-adaptive`는 제거됐다. 이전 구성은 **자동으로 새 Target에 매핑되지 않는다.** `make reset`은 인증 설정과 전체 Runtime 상태까지 지우므로 이 이전에 사용하지 않는다.

1. **기존 버전에서** `make down`을 실행해 해당 Checkout 소유 컨테이너를 중지한다. 이미 새 버전으로 전환했다면 `python scripts/ops/compose_ownership.py down`으로 동일 Checkout 소유 리소스를 정리한다. 다른 Checkout이나 레이블이 없는 컨테이너는 임의 삭제하지 않는다.
2. 새 버전의 동일 Checkout에서 원하는 정책을 명시한다. CPU-only는 `cpu`, GPU 우선·CPU 복구는 `fallback`, 자동 복귀는 `automatic`이다. GPU 고정은 `--policy gpu --profile <GPU_PROFILE>`을 사용한다.
3. 실행 전 다음 명령으로 영향을 확인하고, 같은 명령에 `--confirm migrate`를 추가해 적용한다.

```bash
python scripts/ops/migrate_managed_target.py --policy cpu
python scripts/ops/migrate_managed_target.py --policy cpu --confirm migrate
make up TARGET=linux-nvidia-dynamic
```

전환은 `.env`의 **Target·부팅 프로필·실행 정책·Main 내부 URL**만 변경한다. `API_KEYS`, `ADMIN_API_KEYS`, 내부 인증 토큰, 기존 포트 대역, 무관한 `.runtime` 파일과 모델 캐시는 유지한다. 기존 Main 상태 파일은 `.runtime/migrations/`에 백업 후 활성 위치에서 제외해 새 정책을 새로 검증하도록 한다. 백업한 `.env`에는 인증 정보가 있으므로 외부로 공유하지 않는다.

실행 중 컨테이너가 남아 있거나 영속 상태가 손상됐다면 변경하지 않고 실패한다. 완료 뒤 Console과 `/ready`, `/v1/models`로 현재 실행 정책을 확인한다.


## 10.1 배포 authority

Repository가 소유하는 canonical lifecycle은 다음 명령이다.

| 단계 | 명령 | 책임 |
|---|---|---|
| 초기화 + 수렴 | `make up TARGET=<id>` | target·access profile·persistent `.env`, 필요한 image/model cache와 runtime, target-appropriate serving gate 수렴 |


| 기동 | `make up` | target topology 기동과 readiness |
| 상태 확인 | `make status` | Runtime·Gateway·target 상태 확인 |
| 추가 대표 요청 검증 | `make smoke` | 기동 완료 이후 활성 Runtime의 API 경로를 독립적으로 확인 |
| 종료 | `make down` | 선택 target의 실행 리소스 종료 |

`make up` 이후 Runtime start/stop은 Runtime Controller가, Main Model 전환은 Main Model
Control이 소유한다. Configuration 변경은 Configuration Plan/Apply 계약을 따른다.
세부 결정은 [ADR-0037](./adr/0037-local-lifecycle-deployment-authority.md)을 따른다.

---

## 10.2 최초 host 준비

Linux/NVIDIA target의 host에는 최소 다음이 준비되어 있어야 한다.

- Docker / Docker Compose
- NVIDIA driver와 Container Toolkit
- 모델 cache를 저장할 writable 경로
- 필요한 Hugging Face credential
- 외부 registry digest를 사용하는 경우 해당 registry pull 권한

최초 실행은 다음 순서로 진행한다.

```bash
HF_TOKEN=hf_xxx make up TARGET=linux-nvidia-dynamic
make status
```

기본 access profile은 local이다. 다른 접근 의도가 필요하면 `make up ACCESS=...`의
plan/confirm 흐름을 사용한다.

---

## 10.3 image authority

Project-owned image는 local lifecycle이 직접 build할 수 있다.

```bash
make up
```

현재 `.env`의 `PLATFORM_IMAGE` 또는 `VLLM_IMAGE`가 registry digest
(`name@sha256:...`)라면 local build는 그 artifact를 외부 immutable input으로 보고 보존한다.
Local tag/image ID는 repository source에서 다시 build할 수 있다.

Unified vLLM image의 build input은 `configs/vllm_unified_build.yaml`,
`ops/images/vllm-unified/Dockerfile`, 그리고
`scripts/lib/vllm_unified_image.sh`의 canonical source manifest가 소유한다.

Image를 publish하는 절차와 Runtime을 적용하는 절차는 분리한다. 새 digest를 사용하려면
운영자가 persistent image pin을 명시적으로 갱신한 뒤 같은 lifecycle로 수렴시킨다.

---

## 10.4 환경 설정 동기화

Persistent `.env`의 정상 lifecycle ownership은 `make up`에 있다. 동기화만 분리해서 확인하는
maintainer 작업은 다음 implementation mode를 직접 사용할 수 있다.

```bash
python scripts/config/setup_env.py --sync-env --env-file .env
```

configuration sync는:

- 새 canonical key 추가
- 명시적으로 retired된 key 제거
- operator-owned secret과 host-specific 설정 보존
- repository-owned immutable upstream image projection 수렴

을 수행한다.

중요한 host 설정 변경은 Configuration Plan/Apply 또는 운영자 source-control/host backup
정책으로 관리한다.

---

## 10.5 Runtime Startup Profile

Full-stack compose 기동 시 처음부터 활성화할 non-main Runtime 조합은
`configs/deploy_profiles.yaml`이 소유한다.

기본값은 `main_only`이며, Retrieval Runtime도 초기 기동해야 하면 다음처럼 명시한다.

```bash
RUNTIME_STARTUP_PROFILE=retrieval_ready make up
```

Startup Profile은 **초기 desired state**만 결정한다. `compose-up`은 이를
`RUNTIME_STARTUP_DEFERRED_KEYS`와 실행별 `RUNTIME_STARTUP_GENERATION` 내부 directive로
Gateway에 전달한다. 두 값은 operator-facing persistent `.env` 설정이 아니다. 기동 후 Runtime
상태 변경은 Admin Runtime API / Control Plane이 소유한다.

Main Model profile은 별도의 Main Model Control 계약을 사용하며 GPU 제품명 자체를
지원 allowlist로 사용하지 않는다.

---

## 10.6 기동과 readiness

Dynamic Linux/NVIDIA target에서 `make up`은 내부적으로 canonical compose lifecycle을
실행하고 이어서 strict readiness를 확인한다.

```text
.env / target 확인
      ↓
Main Model boot profile resolve
      ↓
Compose preflight
      ↓
Runtime Startup Profile resolve
      ↓
Model cache prepare
      ↓
effective services start
      ↓
make up
```

`make up`은 target-appropriate serving gate를 완료 조건으로 확인한다. 일반 전체 스택의 `ready_full.sh` 경로는 필수 Runtime readiness와 실제 Main Chat 요청 가능 여부를 확인한다. 관리형 CPU-first 정책은 Core readiness 또는 명시적으로 중단한 Main 상태를 보존하며, static target은 외부 Main dependency를 포함한 Gateway readiness를 확인한다. 활성 non-main Runtime의 대표 요청은 독립적인 `make smoke`가 검증한다. 실패하면 terminal에는 요약과 evidence 경로가 남으며, 기본 후속 확인은:

```bash
make logs
```

로 컨테이너·Runtime 상태와 로그를 확인한다.

---

## 10.7 변경 적용

소스 또는 설정을 갱신한 host에서는 변경 성격에 따라 필요한 준비 단계를 다시 실행한다.

일반적인 순서는:

```bash
git checkout <reviewed revision>
make up
make status
```

이다.

이미 immutable registry image를 사용하고 source 변경이 image rebuild를 요구하지 않는 경우
`make up`은 외부 digest를 보존한다.

Main Model 변경은 가능하면 전체 stack 재배포 대신 Main Model Control의 Plan/Apply/Verify
경로를 사용한다. Model Runtime 상태 변경도 Runtime Controller를 사용한다.

---

## 10.8 실패와 복구

복구 authority는 변경 종류에 따라 나뉜다.

| 실패 영역 | 복구 authority |
|---|---|
| Main Model switch | Main Model Control의 last-known-good rollback |
| Model Runtime transition | Runtime Controller의 reviewed transition |
| Configuration mutation | Configuration history / rollback plan |
| Host source version | 운영자가 정상 버전의 소스를 Git 또는 압축본으로 복원한 뒤 canonical lifecycle 재실행 |
| Published image | 운영자가 known-good immutable digest로 pin 복원 후 lifecycle 재실행 |

즉 rollback은 transport가 아니라 **변경을 실제 소유하는 component**에 둔다.

---

## 10.9 원격 운영

SSH, Ansible, CI runner 등 외부 도구를 사용해 원격 host에서 lifecycle을 실행하는 것은 가능하다.

예:

```text
external transport
      ↓
host checkout / package
      ↓
make up / status
```

다만 repository는 SSH credential, source 전송, release symlink, rolling/full mode,
자동 remote rollback을 별도 제품 계약으로 구현하지 않는다.

이 원칙 덕분에 local console에서 실행하든 외부 automation이 호출하든 **동일한 target,
configuration, Runtime Controller, Main Model Control 계약**을 사용한다.
