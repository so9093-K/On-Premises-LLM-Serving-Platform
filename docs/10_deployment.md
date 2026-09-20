# 10. 배포

이 프로젝트에서 배포는 별도의 원격 release state machine이 아니라 **선택한 host에서
target-aware local lifecycle을 실행해 선언된 구성과 실제 Runtime을 수렴시키는 과정**이다.

```text
Repository / Published Images
          ↓
make setup
          ↓
make build
          ↓
make prepare
          ↓
make up
          ↓
make status
          ↓
Control Plane operations
```

자동화와 artifact 생성의 책임 경계는 [9. 자동화 경계](./09_cicd.md), Runtime 구조는
[4. 실행 환경과 모드](./04_runtime_modes.md), 설정 Source of Truth는
[5. 설정 체계와 Source of Truth](./05_configuration.md)를 참고한다.

---

## 10.1 배포 authority

Repository가 소유하는 canonical lifecycle은 다음 명령이다.

| 단계 | 명령 | 책임 |
|---|---|---|
| 환경 준비 | `make setup TARGET=<id>` | target·access profile·persistent `.env` 수렴 |
| image 준비 | `make build` | repository-owned Platform / Unified vLLM image 준비 |
| model 준비 | `make prepare` | 선택 Main Model의 cache/input 준비 |
| 기동 | `make up` | target topology 기동과 readiness |
| 상태 확인 | `make status` | Runtime·Gateway·target 상태 확인 |
| 종료 | `make down` | 선택 target의 실행 리소스 종료 |

`make up` 이후 Runtime start/stop은 Runtime Controller가, Main Model 전환은 Main Model
Control이 소유한다. Configuration 변경은 Configuration Plan/Apply 계약을 따른다.

이 저장소는 더 이상 별도의 `rolling/full` 원격 배포 모드나 release-directory rollback
state machine을 소유하지 않는다. 세부 결정은
[ADR-0037](./adr/0037-local-lifecycle-deployment-authority.md)을 따른다.

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
make setup TARGET=linux-nvidia-dynamic
make build
make prepare
make up
make status
```

기본 access profile은 local이다. 다른 접근 의도가 필요하면 `make setup ACCESS=...`의
plan/confirm 흐름을 사용한다.

---

## 10.3 image authority

Project-owned image는 local lifecycle이 직접 build할 수 있다.

```bash
make build
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

## 10.4 환경 설정과 migration

Persistent `.env`는 `make setup`과 `make sync-env`가 관리한다.

```bash
make sync-env
```

`sync-env`는:

- 새 canonical key 추가
- 등록된 rename migration 적용
- 명시적으로 retired된 key 제거
- operator-owned secret과 host-specific 설정 보존
- repository-owned immutable upstream image projection 수렴

을 수행한다.

배포 전용 `.env` 백업/복원 state machine은 더 이상 없다. 중요한 host 설정 변경은
Configuration Plan/Apply 또는 운영자 source-control/host backup 정책으로 관리한다.

---

## 10.5 Runtime Startup Profile

Full-stack compose 기동 시 처음부터 활성화할 non-main Runtime 조합은
`configs/deploy_profiles.yaml`이 소유한다.

기본값은 `main_only`이며, Retrieval Runtime도 초기 기동해야 하면 다음처럼 명시한다.

```bash
RUNTIME_STARTUP_PROFILE=retrieval_ready make compose-up
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
make ready-full
```

`make ready-full`은 Gateway health/readiness와 대표 inference 경로를 확인한다. 실패하면:

```bash
make compose-diagnostics
```

로 컨테이너·Runtime 상태와 로그를 확인한다.

---

## 10.7 변경 적용

소스 또는 설정을 갱신한 host에서는 변경 성격에 따라 필요한 준비 단계를 다시 실행한다.

일반적인 순서는:

```bash
git checkout <reviewed revision>
make setup TARGET=<same-target>
make build
make prepare
make up
make status
```

이다.

이미 immutable registry image를 사용하고 source 변경이 image rebuild를 요구하지 않는 경우
`make build`은 외부 digest를 보존한다.

Main Model 변경은 가능하면 전체 stack 재배포 대신 Main Model Control의 Plan/Apply/Verify
경로를 사용한다. Model Runtime 상태 변경도 Runtime Controller를 사용한다.

---

## 10.8 실패와 복구

Repository는 더 이상 source release 디렉터리와 symlink를 바꾸는 자동 remote rollback을
제공하지 않는다.

복구 authority는 변경 종류에 따라 나뉜다.

| 실패 영역 | 복구 authority |
|---|---|
| Main Model switch | Main Model Control의 last-known-good rollback |
| Model Runtime transition | Runtime Controller의 reviewed transition |
| Configuration mutation | Configuration history / rollback plan |
| Host source revision | 운영자가 known-good revision으로 checkout 후 canonical lifecycle 재실행 |
| Published image | 운영자가 known-good immutable digest로 pin 복원 후 lifecycle 재실행 |

즉 rollback은 transport가 아니라 **변경을 실제 소유하는 component**에 둔다.

---

## 10.9 Release package

`make package`는 계속 제공한다.

```bash
make package
```

Package는 deterministic release manifest와 materialized payload를 만든다. 용도는:

- 배포 외부 전달물
- archive
- audit
- reproducibility 확인
- 외부 automation 입력

이다.

Package 자체는 Runtime state를 변경하지 않으며 remote deployment protocol을 의미하지 않는다.
External automation이 package를 다른 host로 전달하더라도, Runtime 수렴은 해당 host에서
동일한 canonical lifecycle을 실행해야 한다.

---

## 10.10 원격 운영

SSH, Ansible, CI runner 등 외부 도구를 사용해 원격 host에서 lifecycle을 실행하는 것은 가능하다.

예:

```text
external transport
      ↓
host checkout / package
      ↓
make setup / build / prepare / up / status
```

다만 repository는 SSH credential, source 전송, release symlink, rolling/full mode,
자동 remote rollback을 별도 제품 계약으로 구현하지 않는다.

이 원칙 덕분에 local console에서 실행하든 외부 automation이 호출하든 **동일한 target,
configuration, Runtime Controller, Main Model Control 계약**을 사용한다.
