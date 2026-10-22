# 12. 운영 관리 및 장애 대응

운영자는 내부 Compose/readiness 단계가 아니라 **현재 상태와 증거**에서 시작한다.

```text
이상 감지
   ↓
make status
   ↓
make logs
   ↓
필요한 service raw evidence
   ↓
원인 수정 / Control Plane 작업
   ↓
make up
   ↓
make status
```

일상적인 지표와 Dashboard는 [11. 관측성](./11_observability.md), Main Model 전환과
Runtime 제어는 [6. 모델 운영](./06_model_operations.md), lifecycle과 복구 책임은
[10. 배포](./10_deployment.md)를 따른다.

---

## 12.1 첫 확인: `make status`

`make status`는 target별 구현 차이를 숨기고 현재 operator-relevant state를 요약한다.

```bash
make status
```

full-stack에서는 다음 정보를 중심으로 본다.

- Platform/Gateway readiness
- deployment target과 access profile
- controllable Runtime의 `active / stopped / starting` desired state
- container 관측 상태
- effective topology에서 unavailable인 Runtime
- 현재 readiness가 실패했다면 관련 dependency와 다음 행동

`stopped` 또는 policy상 `unavailable`인 optional Runtime은 곧바로 장애를 뜻하지 않는다.
현재 configuration과 Runtime desired state에서 **필요한 capability가 serving 가능한가**를
기준으로 판단한다.

### 포트 대역 변경과 기존 캐시

포트는 `.env`의 `PLATFORM_PORT_BASE` 하나로 정한다. 기본값 9400에서 Gateway(+0),
Main(+1), Embedding(+2·+3), Prompt Detector(+4), Risk(+5), Grafana(+10)가 정해지며,
Compose 내부 주소·모델 실행 명령·Prometheus 수집 대상도 같은 값에서 계산된다.
소스·문서를 바꾸거나 Node.js·전체 테스트를 실행하지 않는다.

```bash
make up TARGET=<deployment-target> PORTS=9600   # 첫 설치를 9600 대역으로
make ports BASE=9600 PLAN=1                       # 설치된 환경: 변경 내용·포트 충돌만 확인
make ports BASE=9600                              # .env에 기록 (서비스는 그대로)
make up                                           # 새 대역으로 수렴
make status
```

`make up PORTS=9600`도 설치된 환경에서 같은 변경을 한 번에 적용한다. 두 경로 모두
서비스를 건드리기 전에 Host 포트를 검사한다. 이 플랫폼 자신의 컨테이너가 쓰는 포트는
교체 대상으로 보고, 다른 컨테이너나 프로세스가 쓰는 포트는 이름과 함께 알린 뒤 중단한다.
이때 `.env`와 실행 중인 서비스는 바뀌지 않는다. `make down`을 먼저 실행할 필요는 없다.

`GATEWAY_PORT`·`GRAFANA_PORT`에 대역과 다른 값을 직접 지정했다면 대역을 바꿔도 그 값을 유지한다.
`main-llm-vllm`처럼 이 플랫폼이 실행하는 서비스의 내부 주소(`*_BASE_URL`)는 대역 포트에서만
수신하므로, `make up`이 대역과 어긋난 값을 바로잡고 어떤 키를 고쳤는지 표시한다.
외부 Runtime 주소와 인증키는 바꾸지 않는다.

기존 Compose 캐시는 checkout 소유권을 검증한 뒤 재생성 없이 재사용한다.
이전 컨테이너 연결에서 확인한 볼륨 정보는 `.runtime/compose-state/volume-reuse-*.json`에
기록해 일반적인 `down` / `up` 이후에도 보존한다. 소유권이 불명확하거나 다른 checkout이
사용하는 볼륨은 자동 변경하지 않고 오류로 중단한다. 이 재사용 처리는 볼륨에 소유권
라벨을 새로 붙이거나 `purge`의 삭제 범위를 넓히지 않는다.

구버전에서 `Recreate (data will be lost)?`가 보이면 `y`를 입력하지 말고 실행을 중단한다.
볼륨 삭제로 우회하지 말고 최신 기동 스크립트로 재시도한다.
checkout 라벨이 없는 구버전 네트워크에 활성 컨테이너가 있으면 기동 전 검사가 중단한다.
안내에 따라 `make down` 후 `make up`을 실행하면 볼륨은 유지하면서 빈 네트워크를 이관한다.

Gateway 자체가 응답하지 않거나 required dependency가 준비되지 않았으면 `status`는
성공처럼 보이지 않는다. `Attention`에 준비되지 않은 dependency의 오류와 내부 주소를,
`Next`에 확인할 서비스 로그(`make logs SERVICE=main-llm-vllm` 등)를 표시한다.
Gateway에 연결되지 않으면 gateway 컨테이너 상태를 확인하고, `.env`의 포트가 아직
적용되지 않은 경우에는 실행 중인 포트와 함께 `make up`을 안내한다. `Gateway` 줄에는
상태와 함께 접속 주소가 표시된다. `STOPPED / created`인 선택 Runtime은 기동 시 보류된
것이며 필요할 때 Console에서 시작한다.

---

## 12.2 기본 로그: signal만 본다

`make logs`의 기본 목적은 모든 로그를 보여주는 것이 아니라 **지금 확인할 가치가 있는
application event를 좁히는 것**이다.

```bash
make logs
```

기본 출력은 최근 structured request event 중 다음 신호에 집중한다.

- HTTP 4xx/5xx
- `error_code`
- `diagnostic_code`
- readiness failure

정상 요청까지 보고 싶을 때만 범위를 넓힌다.

```bash
make logs ALL=1
```

structured event에는 가능한 경우 다음 필드를 유지한다.

- service
- route
- status code
- latency
- request ID
- error / diagnostic code
- token usage와 upstream response ID
- readiness dependency summary

이 구조를 통해 “로그를 많이 출력해야 진단 가능하다”가 아니라 **필요한 필드가
일관되게 연결돼 있어야 진단 가능하다**는 원칙을 따른다.

Prompt 원문, API key, Authorization header 같은 민감 정보는 일반 진단 근거로 사용하지 않는다.

---

## 12.3 특정 service의 raw evidence

structured event로 원인 범위를 좁힌 뒤 실제 process/runtime 출력이 필요할 때만 raw log를
본다.

```bash
make logs SERVICE=main-llm-vllm
make logs SERVICE=gateway
```

checkout이 소유한 전체 raw service output을 bounded tail로 볼 때는:

```bash
make logs RAW=1
```

실시간으로 한 service를 추적할 때는:

```bash
make logs SERVICE=main-llm-vllm FOLLOW=1
```

raw log는 evidence이지 기본 operator UI가 아니다. 정상 상태 확인을 위해 10여 개
container의 로그를 먼저 훑는 흐름을 만들지 않는다.

Grafana Request Log Explorer와 Loki를 사용할 수 있는 환경에서는 request ID와
`upstream_response_id`를 기준으로 Gateway event와 runtime 원본을 연결한다.

---

## 12.4 `make up` 진행 표시와 실패 시 diagnostic artifact

오래 걸리는 내부 단계(image build, Main Model 다운로드, readiness 대기)는 진행 중에 경과 시간과
그 단계의 마지막 출력 줄을 terminal 한 줄로 갱신한다. 단계가 15초를 넘기면 전체 출력을
`tail -f`로 볼 수 있는 `.runtime/operator-logs/` 경로를 한 번 표시한다. terminal이 아닌 출력(CI,
파일 리디렉션)에서는 줄을 다시 그리지 않고 30초마다 한 줄씩 남긴다. 끝난 단계는 걸린 시간을
함께 표시하고, 성공한 단계의 출력 파일은 지운다.

`make up`의 내부 단계가 실패하면 terminal에는 실패한 단계의 마지막 관련 출력과 전체
evidence 경로가 표시된다.

일반 implementation 단계의 출력은 다음 경로에 보존될 수 있다.

```text
.runtime/operator-logs/
```

full-stack readiness 실패 시 Compose diagnostic evidence는 다음 경로에 저장된다.

```text
.runtime/diagnostics/<timestamp>/
├─ compose-ps.txt
├─ gateway.log
├─ runtime-controller.log
├─ main-llm-vllm.log
├─ ...
└─ unhealthy-services.txt
```

기본 terminal에는 모든 파일 내용을 다시 출력하지 않고 다음과 같은 알려진 신호만
요약한다.

- unhealthy / exited / restarting container
- vLLM batching configuration failure
- KV-cache memory allocation failure
- unsupported FP8 KV-cache 조합
- vLLM engine initialization failure
- container entrypoint executable failure

분류되지 않은 장애도 raw evidence는 그대로 남는다. 분류기의 한계 때문에 evidence를
버리거나 반대로 evidence 전체를 기본 화면에 쏟지 않는다.

내부 단계 stdout/stderr 전체가 필요한 maintainer는 명시적으로:

```bash
PLATFORM_VERBOSE=1 make up
```

을 사용할 수 있다.

---

## 12.5 요청 오류를 좁히는 순서

서비스가 READY여도 특정 요청만 실패할 수 있다.

```text
실패 요청
   ↓
request ID / route
   ↓
status + error_code
   ↓
diagnostic_code / upstream status
   ↓
관련 service raw log
   ↓
runtime/GPU metric
```

대표적인 해석 기준:

| 신호 | 우선 확인 |
|---|---|
| `401 / 403` | auth/access profile, `make auth-status`, `make auth-doctor` |
| `MODEL_UNAVAILABLE` | 해당 Runtime desired state와 effective topology |
| Main Model switch 관련 503 | Main Model operation/gate 상태 |
| `UPSTREAM_*` | 대상 runtime raw log와 upstream response ID |
| queue/latency 증가 | request event latency, vLLM queue, GPU/KV cache |
| repeated 5xx | 같은 diagnostic code가 여러 request에 반복되는지 |

공개 오류 계약은 [API Reference](./reference/api_reference.md)를 따른다.

---

## 12.6 Runtime과 GPU 문제

Runtime 문제는 **desired state → observed state → resource → raw evidence** 순으로 확인한다.

```text
make status
   ↓
GET /admin/runtimes
   ↓
GPU / queue / KV cache metric
   ↓
make logs SERVICE=<runtime>
```

전체 Runtime desired state와 resource projection:

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/runtimes
```

Main Model state와 active profile은 Main Model Control API에서 확인한다.

Runtime 로그에서 자주 의미가 큰 패턴:

| 패턴 | 의미 |
|---|---|
| `No available memory for the cache blocks` | KV-cache/GPU memory allocation 실패 |
| `Engine core initialization failed` | vLLM engine 초기화 실패; GPU/resource policy 확인 |
| `max_num_batched_tokens ... smaller than max_model_len` | batching configuration 불일치 |
| `kv-cache is not supported with fp8 checkpoints` | runtime image와 KV-cache 설정 조합 오류 |
| repeated restart / OOM | resource budget, driver/runtime, host memory 확인 |

GPU budget과 Runtime activation/eviction 정책은 [6. 모델 운영](./06_model_operations.md)을 따른다.

---

## 12.7 Main Model 전환 문제

Main Model 변경은 일반 lifecycle 재시작과 분리된 Control Plane operation이다.

```bash
curl -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://127.0.0.1:9400/admin/main-model/operations/<operation_id>
```

확인할 항목:

- operation status/stage
- active profile
- gate 상태
- target container observed state
- validation/canary 결과
- rollback 수행 여부
- 마지막 오류/진단 정보

전환 실패를 이유로 project state 전체를 reset하지 않는다. 해당 operation의 rollback과
Main Model Control이 소유한 복구 경계를 먼저 사용한다.

---

## 12.8 인증·접근 문제

예상하지 못한 401/403 또는 host bind 문제는 현재 managed profile부터 확인한다.

```bash
make auth-status
make auth-doctor
bash scripts/compose/compose_config.sh
```

인증 primitive를 직접 바꿔야 하면 plan을 먼저 본다.

```bash
make auth-plan MODE=<auth-mode>
```

일반 사용자의 접근 intent는 `make up ACCESS=local|private|edge`가 소유한다. Host
exposure topology는 private_network 하나이며 raw runtime/operations endpoint를 여는
별도 operator mode는 없다.

---

## 12.9 복구와 재검증

구성이나 source를 수정했거나 Runtime을 복구한 뒤 정상 lifecycle은 다시 `make up`으로
수렴한다.

```bash
make up
make status
```

`make up`은 필요한 artifact 준비와 service reconciliation 뒤 target이 소유한 serving gate를
완료해야 성공한다. managed dynamic target은 필수 Runtime readiness와 실제 Main Chat 경로를,
static target은 외부 Main dependency를 포함한 Gateway readiness를 확인한다.
대표 API·non-main 모델의 추가 검증은 `make smoke`가 독립적으로 소유한다.
검증 명령의 누락이나 실패가 정상 기동 중인 서비스를 중단시키지는 않는다.
배포 승인 시 추가 Smoke 결과를 요구할지는 배포 정책이 정한다.

GPU/runtime 자체가 변경된 qualification 작업이면 그때만 developer/maintainer 검증인
`make runtime-validate`를 추가한다.

복구 완료 기준:

- `make up` 성공\n- `make status`에서 required dependency가 READY
- 필요한 Runtime이 의도한 desired state
- 동일 error/diagnostic code의 재발이 없음
- GPU/queue/KV cache가 운영 범위
- 변경 대상 capability의 실제 요청이 정상

---

## 12.10 Reset과 purge를 장애 복구와 혼동하지 않는다

`reset`과 `purge`는 진단 명령이 아니다. 일반 장애를 만날 때 먼저 실행하면 원인 evidence를
지우고 불필요한 image/model download를 유발할 수 있다.

### Local state 초기화

```bash
make reset
make reset CONFIRM=reset
```

`reset`은 configuration/runtime state와 저비용 local artifact를 초기화하지만
project-built image, repository-local model cache와 Docker volume은 보존한다.

### Project-owned artifact 폐기

```bash
make purge SCOPE=cache
make purge SCOPE=cache CONFIRM=purge

make purge SCOPE=all
make purge SCOPE=all CONFIRM=purge
```

`purge`는 plan-first이며 project ownership이 증명되는 artifact만 제거한다. global
Hugging Face cache, daemon-wide BuildKit cache와 unrelated Docker resource는 제거하지 않는다.
Docker 볼륨·네트워크·로컬 build image는 `ai_model_serving.checkout` 라벨이 현재 checkout과
일치해야 삭제한다. 프로젝트 이름만 같거나 라벨이 없는 기존 자원은 보존한다.
macOS launchd 해제에 실패하면 Reset은 `.env`·`.venv`·`.runtime`을 삭제하지 않는다.
세부 소유권 규칙은 [ADR-0057](adr/0057-checkout-owned-cleanup.md)을 따른다.

---

## 12.11 Operator command reference

| 목적 | 명령 |
|---|---|
| 시작/현재 상태로 수렴 | `make up` |
| 포트 대역 변경 | `make ports BASE=<대역>` → `make up` |
| 현재 상태와 policy state | `make status` |
| 오류/readiness structured event | `make logs` |
| 모든 structured request event | `make logs ALL=1` |
| 특정 service raw evidence | `make logs SERVICE=<id>` |
| checkout 실행 리소스 정지 | `make down` |
| local state 초기화 | `make reset` |
| project-owned artifact 폐기 | `make purge SCOPE=cache|all` |

정상 operator lifecycle은 이 표에서 끝난다. 내부 readiness와 Compose diagnostics는
`make up`의 구현이며, Smoke는 독립적으로 실행하는 운영 검증이다.
검증을 수행할 때는 `make smoke`를 사용한다.

---

## 12.12 구현과 evidence 위치

| 영역 | 구현 / evidence | 역할 |
|---|---|---|
| Operator convergence | `scripts/platform_cli.py` | target resolution, artifact 준비, startup/readiness orchestration |
| Structured event | `.runtime/request-events/*.jsonl*` | request/error/readiness event의 host 원본 |
| Operator step output | `.runtime/operator-logs/` | 실패한 내부 단계의 전체 stdout/stderr |
| Full-stack diagnostics | `.runtime/diagnostics/` | service state와 bounded raw log evidence |
| Strict readiness | `scripts/ops/ready_full.sh` | `make up` 내부 serving gate |
| Representative smoke | `make smoke` → `scripts/ops/smoke_test.sh` | 기동과 독립적인 active/effective Runtime inference 검증 |
| Compose diagnostics | `scripts/compose/compose_diagnostics.sh` | raw evidence 보존 + known-pattern summary |
| Runtime qualification | `scripts/validation/runtime_validation.py` | live GPU/runtime 검증 |

관련 문서:

- [4. 실행 환경과 모드](./04_runtime_modes.md)
- [5. 설정 체계와 Source of Truth](./05_configuration.md)
- [6. 모델 운영](./06_model_operations.md)
- [8. 테스트와 검증](./08_testing_validation.md)
- [10. 배포](./10_deployment.md)
- [11. 관측성](./11_observability.md)
- [ADR-0039](./adr/0039-operator-intent-lifecycle-and-diagnostics.md)
- [API Reference](./reference/api_reference.md)
