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

Gateway 자체가 응답하지 않거나 required dependency가 준비되지 않았으면 `status`는
성공처럼 보이지 않고 `Attention`과 함께 `make logs`를 다음 행동으로 제시한다.

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

## 12.4 `make up` 실패 시 diagnostic artifact

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

## 12.8 인증·노출 문제

예상하지 못한 401/403 또는 host port 노출은 현재 managed profile부터 확인한다.

```bash
make auth-status
make auth-doctor
make exposure-status
```

변경은 plan을 먼저 본다.

```bash
make auth-plan MODE=<auth-mode>
make exposure-plan MODE=<exposure-mode>
```

일반 사용자의 접근 intent는 `make up ACCESS=local|private|edge`가 소유한다. 개별
auth/exposure apply는 Advanced/legacy primitive이며 managed Access Profile을 종료하는
변경이 될 수 있다.

---

## 12.9 복구와 재검증

구성이나 source를 수정했거나 Runtime을 복구한 뒤 정상 lifecycle은 다시 `make up`으로
수렴한다.

```bash
make up
make status
```

`make up`은 필요한 artifact 준비, service reconciliation, readiness와 representative
inference smoke까지 완료해야 성공한다. 별도의 ready/smoke operator command를 추가로
실행해야 배포가 완료되는 구조가 아니다.

GPU/runtime 자체가 변경된 qualification 작업이면 그때만 developer/maintainer 검증인
`make runtime-validate`를 추가한다.

복구 완료 기준:

- `make up` 성공
- `make status`에서 required dependency가 READY
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

---

## 12.11 Operator command reference

| 목적 | 명령 |
|---|---|
| 시작/현재 상태로 수렴 | `make up` |
| 현재 상태와 policy state | `make status` |
| 오류/readiness structured event | `make logs` |
| 모든 structured request event | `make logs ALL=1` |
| 특정 service raw evidence | `make logs SERVICE=<id>` |
| checkout 실행 리소스 정지 | `make down` |
| local state 초기화 | `make reset` |
| project-owned artifact 폐기 | `make purge SCOPE=cache|all` |

정상 operator lifecycle은 이 표에서 끝난다. 내부 readiness, smoke, Compose diagnostics와
clean script는 `make up`의 구현 또는 maintainer 도구다.

---

## 12.12 구현과 evidence 위치

| 영역 | 구현 / evidence | 역할 |
|---|---|---|
| Operator convergence | `scripts/platform_cli.py` | target resolution, artifact 준비, startup/readiness orchestration |
| Structured event | `.runtime/request-events/*.jsonl*` | request/error/readiness event의 host 원본 |
| Operator step output | `.runtime/operator-logs/` | 실패한 내부 단계의 전체 stdout/stderr |
| Full-stack diagnostics | `.runtime/diagnostics/` | service state와 bounded raw log evidence |
| Strict readiness | `scripts/ops/ready_full.sh` | `make up` 내부 serving gate |
| Representative smoke | `scripts/ops/smoke_test.sh` | active/effective Runtime inference 검증 |
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
