# ADR-0054: 관리형 CPU/GPU Main Runtime 자동 선택

## Status

Accepted

## Context

최초 실행 후보만 선택하면 실제 GPU 적재 실패와 운영 중 GPU 장애를 복구할 수 없다.
Core 운영 기능의 생존과 추론 준비 상태는 서로 다른 계약이며, 자동 복구도 진행 중인
요청과 모델 검증을 보호해야 한다. Docker 실행 권한을 Gateway에 주는 방식은 피한다.

## Decision

- Linux 최초 `TARGET=auto`는 `linux-adaptive`를 설정한다. 기존 `.env`의 Target은
  유지한다. 명시적인 GPU Dynamic·CPU Managed·외부 Static Target은 각 Lifecycle을 소유한다.
- 관리형 Linux 기동은 Platform image 준비 후 Gateway·로컬 Risk를 먼저 기동한다.
  모델 image·캐시·메모리 Admission 실패로 Core를 중지하지 않는다. `/health`와
  Console은 Core 생존을, `/ready`는 실제 필요한 추론 준비 상태를 나타낸다.
- Adaptive Target은 CPU Qwen3 GGUF와 GPU Gemma E4B를 기존 Catalog에서 구성한다.
  CPU는 고정 Image Digest·모델 Revision·SHA-256, RAM Admission과 4 GiB 컨테이너
  제한을 사용한다. CPU에 GPU 장치를 부여하지 않는다.
- Compose는 CPU Main 템플릿을 처음 한 번 생성한다. 이후 재실행은 기존 Main을
  재생성하지 않는다. Controller가 같은 Compose service와 내부 endpoint에서 CPU/GPU를
  교체한다. Gateway는 Docker Socket을 갖지 않는다.
- 자동 제어도 기존 MainModelManager의 준비 → Gate 차단 → Drain → 교체 → 실제
  응답 Canary → 상태 Commit을 사용한다. 교체 실패는 이전 Profile을 재생성·재검증한
  뒤 Gate를 연다. 양쪽 검증이 실패하면 Gate를 닫고 Core에서 상태를 진단한다.
  재시작 복구도 Adaptive에서는 Drain을 생략하지 않는다.
- 자원 관측 서비스는 NVIDIA utility 권한으로 GPU별 free/total VRAM을 읽는다.
  Socket·Host Port·모델 실행 권한은 없다. Controller는 고정 내부 endpoint의
  인증된 최신 관측만 사용하며, 관측 불가는 충분한 GPU 자원으로 해석하지 않는다.
- GPU 시작은 장치별 최소 전체 VRAM과 `ceil(total × Profile 예약 비율) + 여유분`을
  만족해야 한다. 여러 GPU의 여유를 합산하거나 다른 프로젝트를 퇴거시키지 않는다.
  실행 중에는 자기 모델이 이미 예약한 메모리를 시작 요구량과 재비교하지 않는다.
  낮은 잔여 VRAM·엔진 장애·관측 실패가 연속되면 CPU로 복구한다.
- GPU 복귀는 연속 안정 관측과 최소 CPU 체류 시간을 요구한다. 실패 재시도 시각은
  Main 상태에 함께 영속화한다. 임계값·주기는 `configs/adaptive_main_model_profiles.yaml`이
  소유한다. 실제 적재 성공은 VRAM 계산이 아니라 Canary가 판정한다.
- 자동 모드의 수동 Profile 전환은 잠근다. 운영자의 Main 중지/시작은 기존 Plan Digest
  검토 경로를 사용하며, 중지 의도는 재시작 후에도 유지한다. Drain 실패 시 중지를 강행하지 않는다.
- Control Plane은 활성 엔진·자동 선택 이유·실측 여유 메모리·재시도 시각을 표시한다.
  GPU 예약 비율은 정책값이며 실측 사용량과 구분한다. 공개 모델·입력·파라미터 한도는
  검증된 활성 Profile을 따르고 Gate가 닫히면 Adaptive Main을 목록에서 제외한다.

## Consequences

| 이점 | 비용과 한계 |
|---|---|
| 모델 장애 중에도 운영 UI와 로컬 Risk 진단 가능 | Platform image와 Docker 자체 장애는 별도 복구 필요 |
| 기존 전환·잠금·Canary·Rollback 계약 재사용 | 엔진 교체와 GPU 준비 동안 새 추론 요청은 503으로 거부됨 |
| 외부 GPU 작업의 소유권 유지 | 모델 적재 후 다른 작업이 VRAM을 선점하는 경합을 완전히 없앨 수 없음 |
| 고정 CPU 모델로 텍스트 서빙 복구 | CPU에서는 GPU의 멀티모달·Tool·문맥·출력 한도를 보장하지 않음 |
| 기존 Main 상태에 자동 선택 정보 영속화 | Gateway 단일 프로세스의 기존 Drain 계약을 사용하며 다중 Replica 전환은 별도 설계 필요 |

Native 프로세스 감독이나 별도 Router·전환 Journal을 추가하는 대안 대신 기존 Docker
감독과 Main 전환 권위를 선택한다. Docker Socket의 `:ro` mount는 API 쓰기 권한을
제한하지 않으므로 Controller는 기존의 신뢰된 내부 운영 경계에 둔다.

## Related

- [ADR-0053](0053-model-optional-deployment-and-cpu-static-serving.md)
- [모델 운영](../06_model_operations.md)
- [자동 Runtime 운영](../guides/adaptive-runtime.md)
