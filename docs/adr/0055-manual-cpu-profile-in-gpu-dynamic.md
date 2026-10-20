# ADR-0055: GPU Dynamic의 관리형 CPU 수동 선택

## Status

Accepted

## Context

GPU Dynamic에서 GPU 모델만 선택할 수 있으면, 운영자가 CPU 서빙을 원해도 별도 Target으로
이전해야 한다. CPU/GPU 자동 제어 여부와 수동 모델 선택 범위는 다른 결정이다.
CPU를 GPU 예약률 0%의 vLLM 모델로 취급하면 엔진 설정·예산·재시작이 어긋날 수 있다.

## Decision

- Gateway는 Main의 Compose health를 기동 의존성으로 갖지 않는다. GPU가 준비되지 않아도
  운영 UI와 Scalar에서 상태를 확인하고 CPU 후보를 선택할 수 있다. 추론 준비는 Gate와 `/ready`가 소유한다.
- `linux-nvidia-dynamic`은 기존 GPU 후보와 고정 CPU GGUF 후보를 함께 제공한다.
  CPU 선택은 기존 MainModelManager·상태 저장소·동일 service/endpoint를 사용한다.
  자동 GPU 복귀나 CPU 자동 복구는 `linux-adaptive`의 별도 권한으로 유지한다.
- Main Catalog는 CPU Serving Catalog를 참조한다. CPU 모델 신원·Revision·SHA-256은
  `cpu_model_artifact.yaml`이 소유하며 Dynamic과 Adaptive가 같은 프로필 조립을 재사용한다.
- 수동 전환도 준비 → Gate → Drain → 교체 → Canary → Commit을 따른다. 준비 단계의
  RAM·Artifact·image 실패는 이전 GPU를 유지한다. 교체 실패는 기존 Rollback으로 복구한다.
  CPU에는 GPU 장치를 부여하지 않고 기존 4 GiB RAM·PIDs 제한을 적용한다.
- CPU는 `gpu_required=false`, 예약량 0의 Lifecycle 참여자로 표현한다. GPU 요구량 0은
  일반 GPU Admission에서는 계속 잘못된 입력이다. CPU 준비는 RAM을 검사하며 GPU 관측
  실패나 GPU 예산 부족으로 차단하지 않는다. CPU 시작은 GPU Runtime을 퇴거시키지 않는다.
  GPU로 복귀하는 수동 요청은 기존 GPU Admission을 통과해야 한다.
- 엔진 교체는 대상 image의 Entrypoint·환경을 사용한다. 원래 Docker GPU 장치 요청은
  CPU 컨테이너의 Controller 소유 label에 보존해 Controller 재시작 뒤에도 복원한다.
  CPU로 부팅할 때는 생성 Compose override의 `!reset`으로 기존 GPU 장치 목록을 제거한다.
  초기 GPU 장치 구성은 canonical Compose에서 가져온다.
- `.runtime/cpu-models`는 Controller에서 준비하고 Main에는 읽기 전용으로 연결한다.
  기존 컨테이너에 이 mount가 없으면 CPU 준비를 거부하고 `make up`으로 갱신하도록 안내한다.
- Control Plane은 실제 모델·실행 엔진·CPU 선택 가능 여부와 입력/토큰 한도를 표시한다.
  GPU 예약 표시에서 CPU는 해당 없음으로 구분한다. Scalar는 Target별 수동/자동/외부 운영
  모드와 CPU 후보·요청 예시를 설명한다. Playground는 활성 모델의 공개 메타데이터를 사용한다.
- `/v1/models`의 모델명·체크포인트·엔진·문맥 한도는 활성 Profile에서 함께 투영한다.
  Controller를 관측할 수 없으면 모델 신원을 추정하지 않는다. 외부 CPU Target은 관리형
  Qwen 체크포인트가 실행 중이라고 표시하지 않는다.

## Consequences

| 이점 | 비용과 한계 |
|---|---|
| Dynamic Target 이전 없이 CPU 수동 선택 | Dynamic 최초 배포의 NVIDIA 실행 조건은 계속 필요 |
| 기존 전환·Drain·Canary·Rollback 재사용 | 엔진 교체 동안 신규 요청은 일시 거부 |
| CPU 선택과 GPU 예산의 명확한 분리 | CPU 준비에 RAM·디스크·image와 Artifact 접근 필요 |
| 기존 Main 상태가 수동 선택을 재시작 뒤 복원 | CPU 부팅의 장치 제거는 Compose `!reset` 지원 필요 |

CPU 전환은 보조 Runtime의 기동이나 배포의 기능 노출 정책을 자동 변경하지 않는다.
명시적인 Host Resource Variant에 연결된 보조 Runtime 구성 제한은 기존 배포 정책을 따른다.
이 변경의 격리 CPU 실추론은 GPU 모델의 실장비 왕복 전환이나 다른 GPU의 Qualification을
대신하지 않는다. CPU 프로필의 `unverified`를 유지한다.

## Related

- [ADR-0054 자동 선택](0054-managed-cpu-gpu-runtime-selection.md)
- [모델 운영](../06_model_operations.md)
- [수동 CPU 검증](../resources/manual_cpu_model_validation.md)
