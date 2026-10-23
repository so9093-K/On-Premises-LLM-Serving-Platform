# 6. 모델 운영

AI Model Serving Platform의 Main Model 운영은 **현재 상태 확인 → 프로파일 선택 → 모델 전환 → 전환 결과 확인 → 서비스 검증** 순서로 진행한다.

외부 Chat API는 `local-main`이라는 논리 model ID를 유지하고, 실제 Main Model runtime은 선택된 profile에 따라 model, revision, runtime image, vLLM command를 적용한다.

이 장에서는 운영자가 Main Model을 확인하고 시작·중지·전환하는 방법을 설명한다. **6.1~6.8은 일반 운영 흐름**, 6.9 이후는 전환 상태와 runtime 세부 정보를 다룬다. Runtime 실행 구조는 [4. 실행 환경과 모드](./04_runtime_modes.md), profile과 GPU 설정은 [5. 설정 체계와 Source of Truth](./05_configuration.md), Admin API contract는 [API Reference](./reference/api_reference.md)에서 확인한다.

---

### 재검증과 요청 차단

Runtime Controller가 다시 시작되거나 Main Runtime이 외부에서 교체되면 이전
`gate=open` 기록을 현재 인스턴스에 대한 검증 증거로 재사용하지 않는다.
현재 Profile의 실행 계약(이미지와 Resource Variant·GPU 비율까지 적용된 최종 실행
인자)과 실행 중 컨테이너의 시작 신원을 Canary 전후에 확인한다. 같은 모델이라도
Context·Batch·GPU 예약 인자가 다르게 실행됐다면 Profile 불일치로 보고 Gate를
닫는다. Docker 시작 신원·Profile의 관측 자체가 실패해도
기존 Gate 개방은 폐기하며, 관측 복구 후 Canary를 통과해야 다시 개방한다.
공개 모델 별칭 `local-main`의 API 성공만으로 실제 프로필 일치를 보증하지 않는다.

Control Plane의 **메인 모델**에서 현재 활성 Profile, 관측 Profile, 실제
Runtime 상태와 요청 Gate를 함께 확인한다. 불일치·차단이 지속되면
Runtime Controller 로그와 최근 Model Operation을 검토하고, 정상 실행 신원을
복구한 뒤 검증 결과를 재확인한다. 검증되지 않은 컨테이너를 반복 재시작하거나
Gate를 임의로 개방하지 않는다. 재시작 감지는 주기적으로 수행되므로 다음
관측까지 지연될 수 있으며, 원격 실행의 Fencing은 지원하지 않는다.

## 6.1 모델 운영 흐름

일반적인 Main Model 변경 작업은 다음 순서로 진행한다.

```text
현재 상태 확인
    ↓
전환할 Profile 선택
    ↓
GPU 자원 확인
    ↓
모델 전환 요청
    ↓
전환 상태 확인
    ↓
Gateway Ready 확인
    ↓
Chat Smoke Test
```

Main Model control path는 Gateway와 Runtime Controller를 사용한다.

```text
Operator
   │
   │ Admin API
   ▼
Gateway :9400
   │
   ▼
Runtime Controller :8080
   │
   ├─ Main Model state
   ├─ GPU admission
   ├─ request drain
   └─ Docker lifecycle
          │
          ▼
   main-llm-vllm :9401
```

| 계층 | 역할 |
|---|---|
| **Gateway** | Admin API 제공, 인증, control 요청 전달, Chat gate 적용 |
| **Runtime Controller** | Main Model 상태, 모델 전환, GPU admission, Docker lifecycle 관리 |
| **Main Model Runtime** | 선택된 profile의 vLLM inference 수행 |
| **Main Model State** | active profile, runtime state, gate, 최근 operation 기록 유지 |

모델 profile 변경은 `POST /admin/main-model/switch`, runtime 시작·중지는 `PATCH /admin/runtimes/main`을 사용한다.

---

## 6.2 현재 상태 확인

모델 운영을 시작할 때는 Main Model 상태와 전체 runtime 상태를 먼저 확인한다.

### Main Model 상태

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/main-model
```

주요 필드는 다음과 같다.

| 필드 | 의미 |
|---|---|
| `active_profile` | 마지막으로 검증을 통과해 control-plane에 기록된 Main Model profile |
| `runtime_state` | control-plane에 기록된 lifecycle 상태인 `active` / `stopped` |
| `gate` | 신규 Chat 요청의 `open` / `closed` 상태 |
| `last_known_good_profile` | 마지막으로 정상 검증을 통과한 profile |
| `profile_locked` | Admin API profile 변경 잠금 상태 |
| `last_operation` | 가장 최근 모델 전환 operation |
| `observed_runtime` | 조회 시점 Docker 관측값. 실제 컨테이너 상태·health·profile, image ref/image ID, image label에서 읽은 runtime engine/version을 포함 |

`active_profile`과 `runtime_state`는 Docker를 매번 조회해 계산한 값이 아니다. Main Runtime이 운영 API 밖에서 재시작되거나 사라진 사실을 Controller가 관측하면 기존 검증을 계승하지 않고 Gate를 닫으며, 실제 컨테이너 신원·기능 검증 후에만 다시 개방한다. 재검증 실패 시에는 요청이 일시적으로 503으로 거부될 수 있고 Gate는 닫힌 상태를 유지한다. ([ADR-0050](adr/0050-resource-scoped-serving-authority.md))

실제 서비스
가능 여부는 `observed_runtime.status=ready`, `observed_runtime.health=healthy`, 그리고
`gate=open`을 함께 확인한다. `observed_runtime.image_ref`는 컨테이너 생성에 실제 사용된
image 참조이고, `image_id`는 Docker local image ID다. `image_digest`는 실행 image의
registry/distribution digest이며 단일 값을 관측할 수 없으면 `null`이다. `runtime_engine.version`은 Unified image의
`ai_model_serving.vllm_version` label을 읽으며 label이 없는 image의 버전을 추측하지 않는다.
Docker를 읽지 못한 경우에는 응답 전체를 성공처럼 보이게
유지하지 않고 `observed_runtime.status=unknown`과 `error`를 반환한다.

### Runtime 상태와 GPU budget

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/runtimes
```

이 API에서는 Main Model과 non-main Model Runtime의 상태, GPU budget 사용량을 함께 확인할 수 있다.
GPU 예산에서 `paused`·`restarting`은 실제 Serving 준비와 무관하게 예약 중으로 계산한다.
종료·부재를 확인한 상태만 예약 해제로 계산하며 Docker 상태가 불명확하면
예약이 비었다고 추정하지 않고 503으로 거부한다. `paused`·`restarting`은
자동 퇴거 및 Start/Stop Plan으로 정상 처리할 수 없으므로 Docker에서 상태를
복구한 뒤 다시 계획한다. 실행 중인 대상 Runtime에 선행 Runtime을 추가로
시작하는 경우에도 기존 대상의 GPU 예약을 유지하며, 검토한 퇴거 대상이
적용 시 달라졌다면 다시 계획해야 한다. 이 비율은 실측 VRAM 사용량이 아니다.

Runtime 시작·중지의 Plan/Apply 요청·변경 감지·결과 확인은 [Runtime Plan/Apply 계약](./reference/runtime_transition_plan.md)을 따른다.

---

## 6.3 모델 프로파일 선택

Main Model Profile은 `local-main` runtime을 어떤 model과 실행 조건으로 구성할지 정의한다.

```text
Main Model Profile
   ├─ model / revision
   ├─ runtime image
   ├─ vLLM command
   ├─ context / concurrency
   ├─ GPU utilization
   ├─ modality capability
   ├─ compatibility status
   ├─ qualification status
   └─ resource policy (reference / explicit override)
```

Profile의 Source of Truth는 `configs/main_model_profiles.yaml`이다. 과거 실측과 모델 전환 검증의 서술 기록은 [프로필 검증 이력](./resources/main_model_profile_validation_history.md)에서 확인한다. 이 기록은 현재 Runtime 상태나 admission 한도가 아니다.

현재 사용 가능한 profile은 다음 API로 조회한다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/main-model/profiles
```

Profile을 선택할 때는 다음 항목을 확인한다.

- profile ID와 display name
- upstream model과 pinned revision
- runtime image
- GPU VRAM fraction
- compatibility status
- qualification status
- input / output capability
- 현재 active 여부

### Compatibility와 Qualification

Main Model Profile은 기술 호환성과 실제 검증 수준을 별도 축으로 관리한다.

| 축 | 상태 | 운영 의미 |
|---|---|---|
| Compatibility | `compatible` | 현재 deployment/runtime 조합에서 기술적으로 전환 가능한 profile |
| Compatibility | `incompatible` | 현재 deployment/runtime 조합과 기술적으로 호환되지 않아 전환 불가 |
| Compatibility | `unknown` | 기술 호환성을 아직 확정할 정보가 부족함 |
| Qualification | `verified` | maintainer가 실제 장비에서 검증을 마쳤다고 선언함 |
| Qualification | `unverified` | 아직 실제 장비 검증을 마치지 않았음 |

`configs/main_model_profiles.yaml`과 여기서 참조하는 CPU 공통 프로필
`configs/cpu_main_model_profiles.yaml`, Admin API는 동일한 canonical 상태를 사용한다.
`compatibility.status`는 기술 호환성만, `qualification.status`는 실제 장비 검증 여부만 표현한다.

전환 가능 여부는 Compatibility가 결정한다. `incompatible`은 전환할 수 없고, 그 외 전환 가능한
profile에서 Qualification이 `verified`가 아니면 switch 요청에 `confirm_unverified=true`가 필요하다.

여기서 Qualification은 **GPU 제품 지원 목록이 아니다.** 현재 GPU 제품에서 직접
검증하지 않았다는 사실만으로 hardware가 unsupported가 되지 않는다. 실제 실행 가능성은
Deployment/Runtime Compatibility와 GPU resource admission, 그리고 start/apply 뒤 runtime validation이
판단한다. GPU 이름·UUID·driver·memory는 관측값이며 primary admission key가 아니다.

새 GPU가 들어왔을 때 reference resource policy를 충족하면 별도 GPU-specific variant나 재qualification
없이 같은 profile을 시도할 수 있다. reference policy가 실제로 맞지 않을 때만 검토된
`resource_variant` override를 추가한다. 세부 원칙은
[ADR-0035](./adr/0035-capability-based-hardware-admission-and-transparent-operations.md)를 따른다.

### Qualification 선언

`qualification.status`는 maintainer가 해당 프로필의 원본 설정에 직접 적는 선언이다
(GPU: `configs/main_model_profiles.yaml`, CPU: `configs/cpu_main_model_profiles.yaml`).
profile을 새로 추가하거나 model ID·revision·`deployed_input`을 바꾸면 `unverified`로 두고,
실제 장비에서 전환과 해당 Backend의 Live 검증이 통과한 뒤 `verified`로 바꾼다.
전용 Runtime 검증 CLI는 품질 체계 초기화에서 제거했다. 현재 `make smoke`는 대표 Gateway API만 확인하며 Backend별 전체 검증과 동등하지 않다. `verified` 선언은 maintainer가 실제 장비에서 모델 신원·변경 범위의 입력/응답·전환 결과를 직접 확인한 범위에 한한다. 어떤 장비에서 무엇을 확인했는지는 profile 주석과
commit/PR 설명에 남긴다. CPU 프로필 검증은 GPU 없는 호스트의 전체 배포 Target 검증이나
다른 Target의 자동 전환 검증을 대신하지 않는다.

별도의 machine-readable 근거 catalog, receipt, 승격 도구는 두지 않는다
([ADR-0042](./adr/0042-remove-qualification-evidence-and-benchmark.md)). 선언이 실제 검증을
넘어서지 않는지는 review가 책임진다. GPU/driver/resource policy가 바뀌었다는 이유만으로
`verified`를 되돌리지 않는다.

### Profile Lock

`MAIN_MODEL_PROFILE_LOCKED=true`이면 `MAIN_MODEL_BOOT_PROFILE`을 기준으로 Main Model profile을 고정한다. 일반 운영에서는 persisted active profile이 다음 기동에도 이어진다.

관련 설정은 [5. 설정 체계와 Source of Truth](./05_configuration.md)에서 설명한다.

---

## 6.4 모델 전환

모델 전환은 **Target 준비 → 기존 요청 Drain → Runtime 교체 → 검증 → 전환 결과 확정** 순서로 진행된다.

```text
Switch 요청
    ↓
Target Profile 준비
    ↓
GPU Admission
    ↓
기존 요청 Drain
    ↓
Runtime 교체
    ↓
Runtime 검증
    ↓
전환 결과 확정
```

### 전환 요청

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"profile":"<profile-id>"}' \
  http://127.0.0.1:9400/admin/main-model/switch
```

정상적으로 접수되면 `202 Accepted`와 `operation_id`를 반환한다.

```json
{
  "operation_id": "<uuid>",
  "status": "pending",
  "reused": false,
  "message": "..."
}
```

### Target 준비

전환 작업은 target profile의 고정 `model_id + revision` snapshot을 공용 model cache에 준비한다. 이 구간에서는 기존 Main Model과 Chat 요청 처리가 유지된다.

필요하면 전환 전에 model snapshot을 미리 준비할 수 있다.

```bash
make main-model-prepare PROFILE=<profile-id>
```

`HF_CACHE_DIR`은 container의 `HF_HOME`에 mount되는 host root를 뜻한다.
준비 명령과 vLLM은 모두 그 아래 `hub/`를 실제 repository cache로 사용한다.

### 기존 요청 Drain

Target 준비가 끝나면 신규 Chat 요청을 잠시 제한하고, 현재 처리 중인 요청이 완료될 때까지 기다린다.

```text
기존 요청  ─────────────────────► 완료

신규 요청  ── 503 ── 503 ──────► 재개
                 모델 전환        Gate Open
```

이 구간의 신규 Chat 요청은 Gateway에서 `503`과 `Retry-After`로 응답한다.

### Runtime 교체

Drain이 완료되면 기존 `main-llm-vllm` container를 종료하고 target profile의 image와 command로 runtime을 다시 구성한다.

### Runtime 검증

새 runtime이 시작되면 서비스 재개 전에 다음 순서로 검증한다.

```text
Container Health
      ↓
/v1/models
      ↓
Text Inference Canary
      ↓
필요한 Media Canary
      ↓
전환 결과 확정
```

필수 검증이 통과하면 새 profile을 현재 활성 profile로 확정하고 Chat gate를 다시 연다.

---

## 6.5 전환 결과 확인

모델 전환은 비동기 operation이므로 `operation_id`로 결과를 확인한다. 최근 보존된 전환 작업은 다음 API에서 최신 순서로 확인할 수 있다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/main-model/operations
```

이 목록은 Main Model state가 보존하는 bounded recent operation projection이며 장기 audit ledger가 아니다. 개별 작업의 현재 상태는 `operation_id`로 조회한다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/main-model/operations/<operation-id>
```

운영 관점에서 중요한 최종 상태는 다음 세 가지다.

| 상태 | 의미 |
|---|---|
| `completed` | target profile 전환 완료 |
| `failed` | target 전환 실패, 필요 시 이전 정상 profile로 복구 완료 |
| `rollback_failed` | target 전환과 이전 profile 복구가 모두 실패 |

`status`와 `stage`는 같은 의미가 아니다. 진행 중에는 둘이 같은 값을 사용할 수 있지만,
terminal failure에서는 `status=failed`를 결과로 기록하면서 `stage`에는 실제 실패가 발생한
단계(예: `preparing`, `draining`, `starting`, `validating`)를 보존한다. 따라서 운영자는
오류 문자열만 읽지 않고 **어느 단계에서 멈췄는지**를 먼저 확인할 수 있다.

전환이 완료되면 Gateway readiness와 실제 Chat 응답을 확인한다.

```bash
curl http://127.0.0.1:9400/ready
```

full-stack에서는 `make status`와 Gateway `GET /ready`로 준비 상태를 확인한다.
`make up`은 선택한 Target의 필수 Readiness를 기동 완료 조건으로 사용한다. 일반 전체 스택은 Main Chat 경로도 확인하고, 추가 모델별 대표 요청 검증은 별도의 `make smoke`에서 실행한다.

마지막으로 실제 Chat inference를 호출해 active Main Model의 응답을 확인한다.

### 재시도 가능한 Switch Request

자동화 환경에서는 `request_id`를 사용해 동일한 switch 요청의 재시도를 안전하게 처리할 수 있다.

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "profile":"<profile-id>",
    "request_id":"deploy-20260811-main-switch"
  }' \
  http://127.0.0.1:9400/admin/main-model/switch
```

유효 기간 안에서 동일 `request_id`와 동일 profile을 다시 요청하면 기존 operation을 반환하고 `reused=true`로 표시한다.

---

## 6.6 GPU 자원 확인

모델을 시작하거나 전환하기 전에 필요한 GPU 자원을 확보할 수 있는지 확인한다. 이 판단 과정이 **GPU Admission**이다.

Main Model과 non-main Model Runtime은 같은 GPU VRAM budget을 사용한다.

```text
GPU Budget
├─ Main Model
├─ Embedding
├─ Korean Embedding
└─ Prompt Injection Detector
```

GPU 상태는 다음 API에서 확인한다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/runtimes
```

주요 budget 정보는 `ceiling`, `used`, `free`로 제공된다. 실제 값은 `configs/gpu_budgets.yaml`을 기준으로 한다.

### Admission 결과

| 결과 | 의미 | 운영 방향 |
|---|---|---|
| `fits` | 현재 자원으로 실행 가능 | 시작 또는 전환 진행 |
| `fits after eviction` | 일부 runtime 정리 후 실행 가능 | stop plan 확인 |
| `infeasible` | 현재 budget으로 실행 불가 | profile 또는 runtime 구성 조정 |

Profile switch에서 자원이 부족하면 필요한 runtime stop plan을 확인한 뒤 자원 구성을 조정하고 다시 전환한다.

**Control Plane → 메인 모델**의 각 후보는 `GPU 예약 비율`과 `실행 전 판단`을 분리해 보여준다.
프로필 조회(`GET /admin/main-model/profiles`)의 `switch_preflight`는 실제 전환 요청이
사용하는 리소스 정책과 동일한 GPU Admission으로 계산한 읽기 전용 결과다.

| 사전 판단 | 의미 | 다음 행동 |
|---|---|---|
| `fits` | 설정된 GPU 예약 예산 검사 통과 | 전환 검토 가능; 시작 뒤 실제 Runtime 검증 필요 |
| `needs_stop` | 낮은 우선순위 Runtime의 예약을 해제하면 예산을 맞출 수 있음 | 안내된 중지 대상을 **별도** 확인·중지 후 재조회 |
| `infeasible` | 중지 가능한 Runtime만으로 예산을 확보할 수 없음 | 모델 정책·동시 실행 구성 재검토 |
| `blocked` | 기술 호환성·배포 잠금·명시적 Resource Variant 조건 또는 다른 모델 전환 진행 중 | 거부 원인을 해결하거나 진행 중인 전환의 완료를 기다린 뒤 재조회 |
| `unknown` | Docker 예약 정보를 확인하지 못함 | 관측 상태를 복구한 후 다시 조회 |
| `current` | 현재 실행 대상으로 선택된 프로필 | 전환 대상이 아님 |

**예약 정책 비율은 GPU 실측 사용량이나 모델 메모리 요구량 추정치가 아니다.**
사전 판단 통과는 실제 가중치 적재·KV Cache·CUDA workspace 할당 성공을 보장하지 않는다.
Docker 예약 관측이 지연되거나 실패해도 조회 전체를 실패시키기보다는 후보를 `unknown`으로 표시한다.
운영 화면은 열린 동안 후보의 실행 전 판단을 주기적으로 갱신하지만, 그 사이의 자원 상태도 달라질 수 있다.
자원 정보가 변할 수 있으므로 서버는 전환을 적용할 때 다시 Admission을 확인하고,
전환 단계에서는 기존 Runtime 검증과 Rollback을 수행한다. 읽기 전용 조회는 Runtime을 정지하지 않는다.

새 hardware에서는 먼저 실제 GPU/resource 상태를 관측하고 reference policy의 feasibility를 판단한다.
제품명이 catalog에 없다는 이유로 거부하지 않는다. 다만 운영자가
`MAIN_MODEL_RESOURCE_VARIANT`를 명시적으로 선택한 경우에는 그 override를 선언하지 않은 profile이
reference policy로 조용히 fallback하지 않도록 fail-closed한다. 이것은 hardware allowlist가 아니라
잘못된 자원 정책 적용을 막는 안전장치다.

같은 variant가 non-main Model Runtime과의 실측된 composition 제약도 가질 수 있다. 이 경우
`configs/runtime_topology.yaml`의 effective topology가 해당 runtime을 control/start 대상에서
제외한다. 현재 `rtx4090-24gb`에서는 Prompt Injection Detector가 제외되며, 단순 비율 admission이
이를 다시 켤 수 없다. reference policy에서는 detector가 일반 controllable runtime으로 유지된다.

Runtime start에서는 `force=true`를 사용해 admission planner가 선택한 낮은 priority runtime을 정지하고 공간을 확보할 수 있다.

```bash
curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"desired_state":"active","force":true}' \
  http://127.0.0.1:9400/admin/runtimes/main
```

GPU budget과 runtime별 reservation 설정은 [5. 설정 체계와 Source of Truth](./05_configuration.md)에서 설명한다.

---

## 6.7 Main Model 시작과 중지

Profile을 유지한 채 Main Model runtime만 시작하거나 중지할 수 있다.

### 중지

```bash
curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"desired_state":"stopped"}' \
  http://127.0.0.1:9400/admin/runtimes/main
```

중지는 다음 순서로 진행된다.

```text
Gate Close
   ↓
Request Drain
   ↓
Runtime Stop
   ↓
VRAM Release
   ↓
runtime_state = stopped
```

현재 active profile은 유지되므로 이후 시작 시 같은 profile을 다시 사용할 수 있다.

### 시작

```bash
curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"desired_state":"active","force":false}' \
  http://127.0.0.1:9400/admin/runtimes/main
```

시작 시 GPU admission과 runtime validation을 수행한 뒤 Chat gate를 연다.

---

## 6.8 실패와 복구

전환 실패 시 복구 방식은 실패 시점에 따라 달라진다.

### Target 준비 중 실패

Model snapshot 준비 단계에서 실패하면 기존 Main Model runtime을 그대로 유지한다.

### Runtime 교체 이후 실패

Runtime 교체 이후 target runtime 시작이나 검증이 실패하면 **직전에 정상 동작한 profile**로 복구(rollback)한다.

```text
Target Runtime Failure
        ↓
이전 정상 Profile 복구
        ↓
Runtime Validation
        ├─ 성공 → Gate Open → operation = failed
        └─ 실패 → Gate Closed → operation = rollback_failed
```

`failed`는 요청한 target 전환이 실패했다는 의미이며, 이전 profile로 서비스가 복구된 상태일 수 있다.

`rollback_failed`에서는 Chat gate가 닫힌 상태로 유지된다. 이 경우 Main Model 상태와 runtime log를 확인하고 정상 profile 복구 작업을 수행한다.

### 주요 실패 유형

| 상황 | 확인 지점 | 운영 방향 |
|---|---|---|
| Profile 확인 실패 | `/admin/main-model/profiles` | profile ID와 qualification 확인 |
| Profile lock | `/admin/main-model` | deployment lock 정책 확인 |
| GPU admission 실패 | `/admin/runtimes` | stop plan 또는 runtime 구성 조정 |
| Model 준비 실패 | model cache / Runtime Controller log | snapshot과 revision 접근 상태 확인 |
| Drain 지연 | in-flight Chat request | 진행 중 요청과 drain 상태 확인 |
| Runtime 시작 실패 | `main-llm-vllm` log | image, command, GPU allocation 확인 |
| Validation 실패 | health, `/v1/models`, canary | runtime과 profile 일치 여부 확인 |
| Rollback 실패 | `last_operation`, runtime log | 정상 profile 복구 후 gate 상태 확인 |

---

## 6.9 상세 전환 상태

일반 운영에서는 [6.4 모델 전환](#64-모델-전환)의 기본 흐름을 기준으로 보면 된다. 전환 문제를 분석할 때는 다음 operation 상태를 사용한다.

| 상태 | 의미 |
|---|---|
| `pending` | 전환 작업 접수 |
| `preparing` | target model snapshot과 cache 준비 |
| `draining` | 기존 요청 완료 대기 |
| `stopping` | 기존 runtime 종료 진행 |
| `starting` | target runtime 생성·시작 |
| `validating` | health와 inference 검증 |
| `rolling_back` | 이전 정상 profile 복구 진행 |
| `completed` | target profile 전환 완료 |
| `failed` | target 전환 실패 또는 rollback 후 복구 완료 |
| `rollback_failed` | target 전환과 이전 profile 복구 모두 실패 |

Main Model의 `runtime_state`와 switch operation 상태는 서로 다른 상태 정보다.

```text
runtime_state
  └─ active / stopped

switch operation
  └─ pending → preparing → ... → completed / failed / rollback_failed
```

### 중단된 전환 복구

Runtime Controller가 switch 중 재시작되면 저장된 operation과 실제 Main Model container를 비교해 상태를 복구한다.

- target profile이 실행 중이고 검증되면 operation을 `completed`로 정리한다.
- 이전 정상 profile이 실행 중이고 검증되면 해당 profile을 활성 상태로 복구하고 operation을 `failed`로 정리한다.
- runtime과 저장된 operation 상태를 일치시키기 어려운 경우 `rollback_failed`로 기록하고 gate를 닫은 상태로 유지한다.

---

## 6.10 Embedding / Risk Model Runtime 운영

Main Model 외 controllable runtime도 Admin API에서 시작·중지할 수 있다.

대표 service key는 다음과 같다.

- `embedding`
- `embedding_ko`
- `prompt_injection_detector`

현재 상태는 다음 API에서 확인한다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/runtimes
```

### Runtime 중지

```bash
curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"desired_state":"stopped"}' \
  http://127.0.0.1:9400/admin/runtimes/embedding
```

### Runtime 시작

```bash
curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"desired_state":"active","force":false}' \
  http://127.0.0.1:9400/admin/runtimes/embedding
```

Start 과정에서는 prerequisite와 GPU budget을 확인하고 필요한 runtime을 startup order에 따라 시작한다.

full-stack `make up` 시 처음부터 활성화할 non-main Model Runtime 조합은 `configs/deploy_profiles.yaml`에서 결정한다. `RUNTIME_STARTUP_PROFILE`이 유일한 startup profile input이며, 값을 생략하면 `main_only`가 적용되어 모든 non-main Model Runtime은 초기 중지 상태가 된다. Retrieval이 즉시 필요하면 `retrieval_ready`를 명시한다.

---

## 6.11 Runtime Artifact와 Capability

Main Model Profile은 model identity와 runtime artifact를 하나의 실행 단위로 관리한다.

| 항목 | 역할 |
|---|---|
| Model / Revision | 실행할 upstream model과 고정 revision |
| Runtime Image | vLLM 실행 환경 |
| vLLM Command | model runtime 실행 인자 |
| GPU Reservation | runtime GPU resource 요구량 |
| Capability | text / audio / video 등 배포 기능 |

Profile에 기록된 revision과 runtime image는 모델 전환 시 함께 적용된다. Gateway가 허용하는 Main Model modality는 active profile의 capability와 runtime validation 결과를 기준으로 한다.

세부 profile 정의는 `configs/main_model_profiles.yaml`, derived vLLM image 구성은 `configs/vllm_unified_build.yaml`에서 관리한다.

---

## 6.12 운영 확인 순서

Main Model 변경 작업은 다음 순서로 확인한다.

| 순서 | 확인 내용 | 방법 |
|---:|---|---|
| 1 | Runtime / GPU 상태 | `GET /admin/runtimes` |
| 2 | 현재 Main Model 상태 | `GET /admin/main-model` |
| 3 | 사용 가능한 Profile | `GET /admin/main-model/profiles` |
| 4 | 모델 전환 | `POST /admin/main-model/switch` |
| 5 | 전환 결과 | `GET /admin/main-model/operations/{id}` |
| 6 | Gateway readiness | `GET /ready` 또는 `make status` |
| 7 | 실제 inference | Chat smoke test |

세부 request / response 형식과 Admin API error contract는 [API Reference](./reference/api_reference.md)를 참고한다.

---

## 6.13 주요 Source of Truth

| 영역 | 주요 파일 | 역할 |
|---|---|---|
| Main Model profile | `configs/main_model_profiles.yaml` | model, revision, image, vLLM command, capability, Gateway 요청 정책, compatibility 정의 |
| GPU budget | `configs/gpu_budgets.yaml` | GPU admission ceiling과 runtime resource policy 정의 |
| Runtime serving policy | `configs/model_serving.yaml` | Gateway runtime 연결, timeout, admission 정의 |
| Runtime Startup Profile | `configs/deploy_profiles.yaml` | full-stack `make up` 후 non-main Model Runtime 초기 deferred 구성 정의 |
| Runtime lifecycle topology | `configs/runtime_topology.yaml` | feature/lifecycle binding과 Main resource-policy composition constraint 정의 |
| Compose topology | `ops/compose/full-stack.private-network.yaml` | Main / non-main Model Runtime container 기본 topology 정의 |
| Main Model state | `.runtime/main-model/main-model-state.json` 또는 deployment state path | active profile, gate, runtime state, switch operation 기록 |
| Runtime control implementation | `src/ai_model_serving/main_model/`, `src/ai_model_serving/apps/runtime_controller.py` | switch, validation, rollback, Docker lifecycle 구현 |
| Gateway Admin API | `src/ai_model_serving/api/routers/gateway_runtime_control.py` | Runtime / Main Model Admin API 제공 |

설정 구조와 적용 방식은 [5. 설정 체계와 Source of Truth](./05_configuration.md)에서 설명한다.

## 자동 CPU/GPU Main 운영

`linux-adaptive`의 후보 선택·복구·중지 의도와 기능 변화는
[자동 Runtime 운영](guides/adaptive-runtime.md)을 따른다. 자동 전환도 이 문서의
Main Gate·Drain·Canary·Rollback을 사용한다. 정책 결정은
[ADR-0054](adr/0054-managed-cpu-gpu-runtime-selection.md)에 기록한다.

## GPU Dynamic에서 CPU 모델 수동 선택

`linux-nvidia-dynamic`의 **메인 모델 → 사용 가능한 프로필**에서 CPU 또는 GPU 후보를
선택해 전환 영향을 검토하고 적용합니다. CPU 후보는 관리형 Qwen GGUF이며 실제 신원과
한도는 Catalog와 화면의 활성 Profile을 확인합니다. CPU 선택은 자동 전환을 켜지 않습니다.
선택한 Profile은 기존 Main 상태에 저장되고 재시작 뒤에도 유지됩니다.

CPU 준비는 RAM·Artifact 무결성·고정 image를 확인합니다. 준비 실패이면 기존 GPU가
요청을 계속 처리하고, 교체에 들어가면 Gate·Drain·Canary·Rollback 계약을 따릅니다.
GPU로 돌아갈 때는 GPU 후보를 다시 검토·적용해야 하며 기존 GPU Admission이 필요합니다.
CPU를 쓴다고 GPU 예산이나 보조 Runtime 기동 정책을 우회하지 않습니다.

기존 배포는 `make up`으로 새 Platform image·Controller와 Main의 CPU cache mount를
반영한 뒤 사용합니다. `/v1/models`에서 실제 모델명·`backend`·`context_window`·지원 입력과
`max_tokens` 한도를 다시 읽으세요. Scalar의 CPU 상태 응답은 사용 방법을 위한 예시입니다.
외부 `linux-cpu-static`은 실제 모델의 준비·실행을 서버 운영자가 소유합니다.

결정과 검증 경계는 [ADR-0055](adr/0055-manual-cpu-profile-in-gpu-dynamic.md)와
[검증 기록](resources/manual_cpu_model_validation.md)을 참고하세요.

## CPU llama.cpp 문맥·출력 프리셋

관리형 CPU 모델의 기본값은 문맥 8,192토큰, 최대 출력 4,096토큰, 동시 요청 1개, Threads 4개다. Context Window는 입력과 출력을 합친 상한이며 최대 출력을 모두 사용할 수 있다는 보장은 아니다.

Runtime Controller를 제공하는 Linux Target의 **메인 모델 → CPU llama.cpp 실행 설정**에서 기본(8K/4K), 경량(4K/1K), 확장(16K/4K) 프리셋을 선택할 수 있다. 설정은 모델별 프로필이 소유하며 선택은 기존 Main Model 전환 기능을 통해 진행된다. 프리셋 적용 중 기존 요청이 잠시 중단되고, 실패 시 이전 모델 복구를 시도한다.

자동 GPU 복구 정책은 기본 CPU 프리셋을 사용한다. 다른 CPU 프리셋을 수동으로 선택하면 CPU 고정 정책이 적용되므로, GPU 자동 복구를 원할 경우 실행 정책을 다시 선택해야 한다. 기본 8K/4K 및 경량·확장 프리셋 모두 변경 후 문맥·출력 상한과 4 GiB 메모리 적합성을 실장비에서 확인하기 전까지 미검증으로 표시한다. 기존 2K/256 CPU 실측 결과를 새 한도의 검증 근거로 재사용하지 않는다.

`linux-cpu-managed`는 Controller가 아닌 Compose가 생명주기를 소유하므로 현재는 Console의 메인 모델 전환 기능을 제공하지 않는다. 해당 Target은 저장소 CPU 프로필의 기본값을 `make up`으로 반영하며, 외부 CPU Runtime(`linux-cpu-static`)의 실행 파라미터는 외부 운영자가 소유한다.

### Console의 모델과 실행 구성 표시

메인 모델 화면은 동일한 `upstream_model_id`, Revision, Runtime backend를 사용하는 프로필을 하나의 실제 모델 아래 묶어 보여준다. CPU 4K/1K·8K/4K·16K/4K는 동일 GGUF 모델의 실행 구성이지 별도 가중치가 아니다. 각 구성의 변경은 기존 Main Model 전환·Canary·Rollback이 적용된다.

Playground의 **이번 요청 최대 출력 토큰**은 `/v1/models`에 광고된 요청 파라미터 범위만 변경하며 실행 인자와 서버의 최대 문맥/출력은 변경하지 않는다. 기존 메인 모델 제어 API는 선언된 프로필 ID 전환만 지원한다. 임의 숫자 토큰 한도 입력을 Runtime에 적용할 수 있는 것처럼 표시하지 않는다. 서버 실행 한도의 변경은 프로필 설정 Source of Truth와 실제 Runtime/Gateway 정책의 동기화, 재시작 복원·Rollback이 필요한 별도 운영 계약이다.

### 관리형 모델의 서버 문맥·출력 한도 직접 조정

`linux-nvidia-dynamic`처럼 Runtime Controller가 모델 재생성을 소유하는 배포에서는 관리자가 모델 실행 구성의 **전환 검토**에서 문맥 토큰 및 최대 출력 토큰을 직접 지정할 수 있다. 입력값은 서버가 다시 검증하고, 실제 엔진 명령(`llama.cpp --ctx-size` 또는 `vLLM --max-model-len`)과 Gateway `max_model_len`·`max_output_tokens`를 같은 변형 프로필로 투영한다.

같은 모델·Revision·이미지의 변형 프로필 ID를 Main Model의 기존 지속 상태에 저장하여 Controller 재시작 뒤 복원한다. 전환은 기존 Gate → Drain → Replace → Canary → Commit 또는 이전 프로필 Rollback 단계로 수행한다. 변경 요청은 미검증 설정 확인을 요구한다. CPU 문맥은 같은 GGUF의 선언된 최대 프리셋 이하, GPU 문맥은 원래 선택한 기준 프로필 상한 이하에서 허용한다. 실제 RAM·GPU 메모리 및 지연 성능은 장비에서 별도 검증이 필요하다.

새 관리형 CPU 설치는 `linux-nvidia-dynamic POLICY=cpu`를 사용한다. 이전 설치의 `linux-cpu-managed`는 Compose 독립 CPU 경로로 계속 동작하지만 이 API로 한도를 수정할 수 없다. 기존 CPU 프리셋 프로필 ID는 상태 복원과 16K 선언 한도의 근거를 위해 유지한다. 외부·Static 런타임은 기존 권한 경계를 유지한다. **Playground의 이번 요청 최대 출력 토큰은 서버 한도 변경이 아니다.**
