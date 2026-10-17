# ADR-0050: GPU 자원별 예약 권한과 배치 근거, 재시작 검증

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR-0018](0018-gpu-vram-admission-and-per-profile-runtime-image.md), [ADR-0031](0031-runtime-controller-docker-authority-boundary.md), [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md), [ADR-0037](0037-local-lifecycle-deployment-authority.md)

## Context

기존 Runtime Controller는 하나의 GPU를 Main Model과 보조 Runtime이 공유한다.
GPU 허용 여부는 vLLM의 예약 **비율**을 합산해 판단한다. 이 비율은 **동일한 물리 GPU 안에서만** 합산할 수 있다.
GPU가 여러 개인 장비나 복수 GPU를 사용하는 모델에 호스트 단위의 단일 예산을 그대로 적용하면 잘못된 배치가 가능해진다.

Linux 동적 배포는 현재 하나의 Compose 프로젝트에 속한 **로컬 Docker 실행 권한**과
파일 기반 Main Model 상태 저장소를 사용한다. `fcntl.flock` 및 프로세스 내부
`asyncio.Lock`은 서로 다른 호스트를 보호하지 않는다. `host_id` 필드를 추가했다는
사실만으로 원격 실행이나 장애 조치를 지원한다고 해석해서는 안 된다.

또한 Runtime Controller 밖에서 컨테이너가 재시작될 경우, 검증에 실패한 인스턴스에
Gateway 요청이 계속 전달될 수 있었다. 이전 검증 지문이 없을 때 관측한 시작 시각만
기록하고 Canary를 생략하던 경로도 있었다.

## Decision

### 1. GPU 예약 예산의 범위는 호스트가 아닌 물리 GPU다

`GpuResourceId(host_id, device_id)`가 GPU 예약 범위의 식별자다. 하나의 호스트에
GPU 두 개가 있으면 예약 범위도 두 개다. 서로 다른 호스트에서 `device_id`가
같더라도 하나의 예산으로 합산하지 않는다. 단일 호스트·단일 GPU는 이 모델의 유효한 한 사례다.

GPU별 허용 및 퇴거 판단의 Source of Truth는 계속
`gpu_budget.plan_activation`이다. 기존 `CONTROLLER_LOCAL_GPU`는 현재 단일
GPU Docker 배포를 위한 **호환성 투영**이며, 실제 탐지된 장치 식별자가 아니다.
서로 다른 GPU 범위의 Participant를 기존 단일 GPU 함수에 함께 전달하면 오류로
거부한다.

로컬 Docker 관측에서 `running`·`paused`·`restarting`은 GPU 예약이
유지된 것으로 취급한다. `created`·`exited`·`not_found`만 예약 해제를
인정하고, 자원 해제를 판단할 수 없는 상태(`dead`·`removing`·`unknown`)는
예산·전환 계획을 거부한다. GPU 예약 유무는 Serving 준비 상태와 별개다.
따라서 `paused`·`restarting`을 정상 실행 중으로 보고 Start Plan을
무조건 성공·No-op 처리하지 않는다. 또한 해당 상태의 Runtime을 자동 퇴거
Victim으로 선택하거나 적용 가능한 Stop Plan으로 광고하지 않는다.
운영자가 Docker 상태를 직접 해소한 뒤 변경 계획을 다시 확인한다.

### 2. 하드웨어 실행 적합성은 호출자가 명시적으로 제공한다

`resource_placement.plan_placement`는 GPU Pool 목록과 실행 가능한 Placement
Candidate를 입력받는다. 하나의 Candidate가 여러 GPU를 예약할 수도 있으며, 각 GPU의
요구량은 **해당 장치에 대해 해석된 비율**로 선언한다.

Planner는 GPU 제품명이나 예약 비율만 보고 모델 호환성, Tensor Parallel 지원,
GPU 간 연결 특성 또는 실제 메모리 적합성을 추정하지 않는다. 이는 호출자 및 실제
Runtime Qualification이 판단한다.

각 GPU에서 기존 Admission 정책을 재사용하고, 퇴거 시에는 복수 GPU Runtime을
일부 Shard만 중지하지 않고 **Runtime 전체**를 중지한다. GPU별 Victim 후보를 합친 후
Runtime 전체가 해제하는 예약량을 모든 관련 GPU에 다시 반영하여 불필요한 중지를 제거한다.
기존 우선순위 정책은 유지하며, 동등한 후보는 결정론적으로 선택한다.

실행 중인 Runtime은 GPU 집합을 조용히 변경할 수 없다. 이동에는 명시적인 중지,
새로운 전환, 실제 실행 상태의 재검증이 필요하다.

### 3. 미리보기 Plan은 변경 실행 권한이 아니다

Placement 미리보기는 GPU Pool Generation, 예약량, Candidate 및 관련 정책 입력을
이용해 결정론적인 Digest를 만든다. 상태가 바뀌면 검토했던 Plan은 무효가 된다.
퇴거가 필요한 계획에는 별도의 명시적 승인이 필요하다.

**Digest 검증은 분산 트랜잭션이 아니다.** 복수 호스트의 실제 적용에는
하나의 권위 있는 예약·Lease 소유자가 제공하는 원자적 비교 후 예약(Compare-and-Reserve),
오래된 Executor를 차단하는 Fencing이 필요하다. `require_current_placement`는
그 소유자의 공유 Lock/CAS 범위에서 예약 Commit까지 실행되어야 한다.
Lock 밖에서 Digest만 다시 계산하는 방법으로는 경쟁 상태를 막을 수 없다.

이번 변경은 메모리 기반 가짜 분산 Lock, 원격 Docker 접근 권한,
전역 Registry 또는 분산 Controller를 도입하지 않는다.
Linux Managed Deployment의 권한은 여전히 로컬 Controller가 소유한다.
정적 배포의 생명주기 권한은 외부 운영자가 유지한다.
공개 `/v1/*` 계약, 논리적 모델 이름 `local-main`, 운영 명령은 변경하지 않는다.

### 4. 로컬 Main Model 상태는 단조 증가 Generation을 사용한다

`MainModelStateStore`는 로컬 Main Model 제어 상태의 유일한 영속 저장 주체다.
상태를 기록할 때마다 Generation을 증가시키며, 오래된 Revision으로 직접 쓰는
작업은 거부한다. `compare_and_update`는 호출자가 읽었던 Generation이 여전히
유효할 때만 갱신한다.

Generation이 없는 기존 Schema v1 상태는 **운영 의도를 초기화하지 않고**
Revision 0에서 시작한다. 잘못된 Generation은 Fail-Closed한다.

원자성의 보장 범위는 **동일한 로컬 파일시스템·상태 디렉터리·파일 Lock을 사용하는
프로세스**까지다. 이 규칙으로 호스트 간 분산 Lease 또는 Fencing을 대체할 수 없다.

### 5. Runtime 실행은 허용 목록으로 제한된 로컬 기능이다

Runtime Controller는 Runtime 전환과 GPU Admission을 판단한다.
`DockerRuntimeExecutor`는 허용된 Compose 서비스를 프로젝트 범위의 Docker 컨테이너
식별자로 해석해 시작·중지·상태 확인을 실행할 뿐이다. Executor에는 별도의 상태
머신을 두지 않는다. Main Model 전환은 기존 Main Model Manager와 Docker Backend가
독립적으로 소유한다. 로그 수집은 프로젝트 범위로 제한된 Docker 관측을 계속 사용한다.

서비스 허용 목록은 Canonical Runtime Topology와 Main Model Profile에서 투영된다.
허용하지 않은 서비스는 Docker API 호출 전에 거부하며, 검색 요청과 결과 모두
Compose 프로젝트 소속인지 검사한다. API 호출자는 임의의 컨테이너 ID, 이미지,
명령, Volume, Mount, Network, Device 또는 원격 Endpoint를 지정할 수 없다.

이 경계는 **Docker Socket 자체의 높은 권한을 Sandbox로 격리한다는 뜻이 아니다.**
실제 Remote Executor를 도입하려면 별도의 인증, 신뢰, Fencing 및 소유권 계약이
선행되어야 한다.

### 6. 외부 Runtime 교체 시 이전 검증 효력은 상실한다

Runtime Controller가 새 인스턴스·인스턴스 소멸·이전 검증 지문 부재를 관측하면
Main Model 요청 Gate를 먼저 닫고 Canary를 다시 수행한다.

Controller 초기화, 명시적 시작, 재시작 감지, Profile 전환, Rollback에서 Gate를
열기 전에 **실행 중인 컨테이너의 시작 신원과 실제 Model Profile(모델·Revision·이미지)**
이 Canary 전후에 모두 일치해야 한다. `local-main`이라는 공개 API Alias의 응답
성공만으로 실제 모델 신원을 증명할 수 없다. 관측 실패, 신원 변경, 검증 실패가
발생하면 Gate를 닫은 채 유지한다. Controller 시작 시에는 저장된 이전
`gate=open`을 현재 인스턴스의 검증 근거로 승계하지 않는다.

재검증 실패는 상한이 있는 Backoff 정책에 따라 재시도한다.
일시적인 Docker Inspect 실패 자체는 인스턴스 교체의 확정 증거는 아니지만,
실행 신원을 검증할 수 없는 상태이므로 Gate를 닫고 진단 이벤트로 기록한다.
관측이 복구되면 이전 개방 상태를 재사용하지 않고 Canary를 다시 통과해야 한다.
**외부 교체 감지는 Polling 기반**이므로 다음 관측까지
시간 창이 남는다. 즉각적인 분산 Fencing이나 무중단 Serving을 보증하지 않는다.

### 7. 실행 계획 거부 및 운영 진단의 계약

여러 선행 Runtime과 Target의 시작 예약량 합계가 단일 GPU Ceiling을 넘으면
잘못된 개별 Fraction이나 처리되지 않은 예외가 아니라 **허용 불가능한 Plan**을
반환한다. Plan과 Apply는 같은 `runtime_transition.plan_runtime_transition`을
호출하며, 선행 Runtime 예약과 기존 Target 예약의 보존·퇴거 대상 선정은
동일한 GPU Admission 정책에서 결정한다. Apply는 로컬 GPU Budget Lock 안에서
동일한 Planner로 상태를 재관측하고 검토한 Digest와 다르면 퇴거 전에 거부한다.
Profile 자체를 교체할 때의 증액 검사는 자동 퇴거 없이 별도로 수행한다.
이 재관측은 Docker 외부 변경에 대한 원자적 Fencing이 아니므로 실제
Docker 상태와 응답 수렴 여부는 별도 Runtime 관측이 책임진다.

Main Model State는 저장된 활성 Profile과 요청 Gate를 소유하고,
Docker Inspect는 실제 컨테이너 관측 결과를 소유한다. Control Plane은
운영 의도, 실제 Profile, 요청 Gate를 별개로 표시한다.
Runtime Plan 변경은 기존 Gateway 오류 Envelope의 `CONFLICT`와
`details.reason=RUNTIME_PLAN_CHANGED` 계약을 따른다.

## Consequences

- 단일 GPU Admission의 판단 함수와 우선순위 정책을 유지한다.
- Runtime Controller의 보조 Runtime 변경은 별도 Docker ID 검색·변경 코드를
  복제하는 대신 허용 목록 기반 Executor를 사용한다.
- Main Model State는 기존 Ledger 권위를 유지하면서 단조 증가 Revision을 제공한다.
- 호스트 한 대의 GPU 두 개, 서로 다른 호스트의 GPU 각 한 개, 복수 GPU Candidate를
  같은 자원 식별 방식으로 표현할 수 있다.
- 권위 있는 장치 Inventory, 영속 Reservation Store, Remote Executor Fencing을
  구현하고 실제 호스트에서 검증하기 전까지 자동 분산 배치를 지원한다고 표시하지 않는다.
- Controller 밖에서 재시작된 모델의 재검증 중에는 일시적으로 요청이 503으로
  거부될 수 있다. Canary 실패 시 Gate를 다시 열지 않는다.
- GPU 예약 비율은 실제 유휴 VRAM 또는 모델 가중치 적합성의 측정 결과가 아니다.
  실제 장치에서의 실행 적합성 검증은 Planner 단위 테스트와 별개다.

## Verification

- GPU Pool 범위 혼합 거부, 후보 적합성, 결정론적 Placement, 여러 GPU 예약,
  Runtime 단위 Victim 퇴거와 중복 퇴거 제거, Generation 변경 시 Plan 무효화.
- Docker Executor의 서비스 허용 목록, Compose 프로젝트 범위, 컨테이너 부재,
  모호한 컨테이너 신원 및 생명주기 변경.
- 기존 단일 GPU Admission 및 Runtime Transition의 회귀 검증.
- 로컬 상태의 Compare-and-Update, 오래된 쓰기 거부, Schema v1 상태 이관.
- 지문 부재·외부 재시작·Canary 실패·검증 중 인스턴스 교체·Backoff 및 성공 복구.
- 프로젝트의 `make check`, 생성 계약 드리프트 검증. 실제 GPU·다중 호스트
  기능은 적절한 물리 환경에서 별도로 검증한다.

## Related

- [ADR-0030](0030-target-architecture-state-and-artifact-boundary.md)
- [ADR-0031](0031-runtime-controller-docker-authority-boundary.md)
- [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md)
- [ADR-0038](0038-resource-aware-secondary-runtime-topology.md)
