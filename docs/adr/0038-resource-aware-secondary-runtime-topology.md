# ADR-0038: 보조 Runtime의 자원 정책을 반영하는 유효 Topology

- Status: Accepted
- Date: 2026-09-21
- Extends: [ADR-0018](./0018-gpu-vram-admission-and-per-profile-runtime-image.md), [ADR-0034](./0034-main-model-host-resource-variant.md), [ADR-0035](./0035-capability-based-hardware-admission-and-transparent-operations.md)
- Follows: [ADR-0037](./0037-local-lifecycle-deployment-authority.md)

## Context

RTX 4090 24GB 실측에서는 `gemma4-e4b-it`와 검토된 `rtx4090-24gb` Main
자원 정책으로 두 Embedding Runtime을 함께 운영할 수 있었다.
하지만 `prompt_injection_detector`까지 추가하는 것은 불가능했다.
이 Detector는 Generation KV Budget을 포함해 약 3.05 GiB가 필요하지만,
Main과 두 Embedding Runtime을 실행한 뒤의 남은 메모리는 그보다 적었다.

기존 GPU Planner는 상대적인 `gpu_memory_utilization` 예약 비율을 사용한다.
일반적인 Admission에는 유용하지만 위와 같은 절대 메모리 구성 한계를 안전하게
추정할 수는 없다. 이에 PR #136에서는 Detector를 전역으로 비활성화했다.
24GB에서의 오류는 막았지만 기준 자원 정책에서는 정상적으로 실행할 수 있는
Runtime까지 제거된 것이다.

ADR-0035는 하드웨어 식별과 자원 실행 가능성을 분리한다.
GPU 제품명은 지원 여부를 결정하는 허용 목록이 아니다.
ADR-0037에서 중복된 원격 배포 상태 머신도 제거했으므로,
자원 제약을 반영한 Topology는 하나의 정규 생명주기로 투영하면 된다.

## Decision

검토된 보조 Runtime의 조합 제약은 `configs/runtime_topology.yaml`의
`unavailable_with_main_resource_variants`가 소유한다.

이 필드는 지정된 Main Model 자원 정책 Override가 선택되어 있는 동안
해당 보조 Runtime을 **유효 Topology에서 사용할 수 없다**는 뜻이다.
특정 GPU 제품·드라이버의 지원 또는 미지원 판정이 아니며,
하드웨어 이름만으로 제약을 추측하지 않는다.

선언된 Topology는 재사용 가능한 기능·생명주기 계약으로 유지한다.
유효 Topology는 명시적으로 선택한 `MAIN_MODEL_RESOURCE_VARIANT`를 적용해 만든다.

- 제약 대상 Runtime은 **유효 투영에서만** `enabled=false`,
  `required=false`, `controllable=false`로 설정한다.
- 시작 Profile은 특정 배포 대상과 무관하게 유지할 수 있다.
  Profile을 해석할 때 사용 불가 항목은 제외하되, 사용 불가 Runtime을 직접 지정한 요청은
  Fail-Closed로 거부한다.
- 유효하게 남은 Runtime은 투영 단계에서 제거된 선행 Runtime에 의존해서는 안 된다.
- 참조한 Resource Variant ID는 Main Model Profile Catalog에 존재해야 한다.
- 운영자 조회용 투영은 제약 대상 Runtime을 '사용 불가' 상태와 안정적인 자원 정책
  사유로 표시할 수 있다. 다만 이를 Controllable·Start·Readiness·Detector·공개
  모델 목록에 다시 넣어서는 안 된다. 이유는 GPU 지원 등급이 아닌 **선택한 자원 정책**을 가리킨다.

동일한 유효 Topology를 Gateway 설정과 `/v1/models`, Risk Signal Service의
Detector 활성화, Runtime Controller의 변경 가능 대상 및 Admission 입력,
Gateway의 원하는 상태 키, Compose 기동 시 Disabled/Deferred 항목 해석,
Smoke Check와 실제 Runtime 검증에 일관되게 사용해야 한다.

체크인된 `model_list_response.schema.json`은 배포 대상에 중립적이다.
모델 ID와 Capability 값은 해당 빌드가 제공할 수 있는 전체 집합이며,
배열 구조는 정적 배포 또는 자원이 제한된 Topology의 Main-only 응답도 허용한다.
현재 유효 Topology에서 필요한 정확한 모델 집합은 정적 Schema가 아니라
Runtime 검증이 판단한다.

현재 실측 사례에서는 `prompt_injection_detector`를 선언상 활성·제어 가능으로
유지하되 `rtx4090-24gb`에서 사용할 수 없는 것으로 명시한다.
따라서 기준 정책은 Prompt Injection Detector를 다시 제공하고,
24GB Override는 안전하게 PII·Secret만 감지하는 위험 신호 경로를 유지한다.

## Consequences

- 한 호스트의 자원 정책에 따라 안전하지 않은 보조 Runtime을 제외하면서도
  기능 선언이나 코드 경로를 전역에서 삭제하지 않는다.
- Runtime Startup Profile은 하드웨어 등급 Catalog가 아닌 운영자의 기동 의도를 나타낸다.
- 하드웨어 관측 근거·Qualification과 실제 Runtime 자원 적합성을 분리한다.
- 정적 예약 비율을 이용한 Admission이 모든 생성형 Runtime의 절대 VRAM 적합성을
  증명한다고 주장하지 않는다.
- 새 제약 조건은 실제 장비의 근거와 검토를 요구한다. 새로운 GPU 제품명이
  관측됐다는 사실만으로 제약을 추가하지 않는다.

## Non-goals

- GPU 제품별 자동 분류 또는 하드웨어 허용 목록
- `configs/gpu_budgets.yaml`의 비율 기반 Admission 대체
- 모델 메타데이터에서 절대 VRAM 요구량 자동 산출
- Main Model Qualification 근거의 의미 변경
- 새로운 Host Inventory 또는 Serving Variant 하위 시스템 도입
