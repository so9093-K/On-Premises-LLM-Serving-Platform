# Runtime Plan/Apply 계약

Runtime의 시작·중지 요청을 검토하고 적용하는 API 계약이다. 실제 운영 순서는 [모델 운영](../06_model_operations.md)을 따른다.

`POST /admin/runtimes/{service_key}/plans`는 런타임을 변경하지 않고 현재 GPU budget과 prerequisite 상태에서 transition 영향을 계산한다.

- `desired_state`: `active` 또는 `stopped`
- `force`: `active` 전환에서 GPU 예산 확보를 위해 낮은 우선순위 런타임을 자동 정지할지 여부. `stopped` 전환에서는 의미가 없으므로 canonical plan에서 `false`로 정규화한다.
- 응답은 `start`, `stop`, `prerequisites`, `impact`, `budget.before/after`, `admissible`, `requires_force`, `plan_digest`를 포함한다.

Plan과 Apply는 서로 다른 admission 구현을 갖지 않는다. Runtime Controller가
`runtime_transition.plan_runtime_transition`에서 기존
`gpu_budget.plan_activation`을 재사용해 Plan을 만들며, `plan_digest`를
PATCH body에 반드시 포함해야 한다. 실제 mutation 직전 GPU budget lock 안에서
**같은 Transition Planner**로 Docker 예약과 선행 Runtime을 다시 관측하고,
Digest가 달라지면 퇴거하지 않고 `409 CONFLICT`와
`reason=RUNTIME_PLAN_CHANGED`를 반환한다. 시작할 Runtime의 VRAM 비용,
선행 서비스 보호, 자동 퇴거 Victim의 계산은 이 Planner가 소유한다.
Profile 교체의 VRAM 변화는 같은 GPU Admission 정책을 사용하지만
Runtime Start Plan과 달리 자동 퇴거를 실행하지 않는다.

Apply는 Plan에서 받은 `plan_digest` 없이는 실행되지 않는다. first-party Admin Console과 외부 자동화 모두 Plan을 먼저 요청하고 반환된 digest를 Apply에 전달한다. 이 digest는 클라이언트가 public projection을 다시 해시하기 위한 값이 아니라, Runtime Controller가 검토 시점의 canonical transition snapshot을 apply-time 재계산과 비교하기 위한 opaque token이다.

## Runtime 부재와 No-op 처리

GPU 예약 해제 상태와 Docker 컨테이너를 시작할 수 있는 상태는 다르다.
Start Plan의 Target 또는 prerequisite가 `not_found`이면 404로 거부하고,
GPU Victim을 먼저 중지하지 않는다. `created`·`exited`는 Docker 컨테이너가
존재하므로 일반적인 Start 정책에 따라 판단한다.

Stop Plan의 `stop=[]`은 Docker 변경이 필요 없는 No-op이며, Apply도
`stopped=[]`로 응답한다. `exited`와 `not_found`를 다시 Stop하지 않는다.
Main Model이 영속 상태 `stopped`이고 Docker 상태 `not_found`이면
Gateway는 컨테이너 관측의 `unavailable` 표시와 무관하게 Stop 완료로
검증한다. 새 컨테이너 생성, 복수 호스트의 원자적 Fencing까지 보장하는 것은 아니다.

## Apply verification과 operation history

Runtime 변경은 Runtime Controller 호출 성공만으로 완료 처리하지 않는다. Gateway는 apply 이후 컨테이너 또는 Main Model의 실제 관측 상태를 다시 읽고 목표 상태와 prerequisite/eviction effect가 수렴했는지 확인한다. 수렴하지 않거나 관측 자체가 실패하면 `RUNTIME_VERIFICATION_FAILED`로 fail-closed하며 operation record는 `verification_failed`로 남는다. destructive mutation은 자동 재실행하지 않는다.

각 Apply는 `rt_<uuid>` operation id를 만들고 actor, request id, service key, desired state, force, 검토된 `plan_digest`, before snapshot, apply result, verification을 journal에 기록한다. 배포에서는 desired-state 파일과 같은 persistent platform state root 아래 `runtime-history/`를 사용하고 temp file + fsync + atomic replace로 terminal record를 갱신한다. source-tree/test 실행처럼 persistent root가 없는 경우 동일 API를 in-memory evidence로 제공하며 record의 `durable=false`로 구분한다.

- `GET /admin/runtimes/operations` — 최신 Runtime transition 이력, cursor pagination
- `GET /admin/runtimes/operations/{operation_id}` — 단일 operation evidence

process가 apply 도중 종료되어 `pending` record가 남으면 다음 Gateway composition에서 이를 성공으로 추정하지 않는다. 실제 apply 시점을 안전하게 재구성할 수 없으므로 `interrupted_after_restart` terminal evidence로 닫고, 운영자는 현재 `/admin/runtimes` 상태를 다시 확인한 뒤 새 Plan을 검토한다.
