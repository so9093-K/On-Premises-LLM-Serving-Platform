# ADR-0053: 모델 없는 기본 배포와 CPU Static Serving

## Status

Accepted

## Context

기존 Linux GPU 배포는 Main Model 캐시와 strict inference 준비를 요구한다.
GPU가 없거나 외부 작업이 VRAM을 사용해도 Gateway·Control Plane·PII/Secret
Risk 기능은 독립적으로 운영할 수 있어야 한다. 기존 app-only는 개발용 모드다.
하드웨어 식별과 GPU 예약 비율은 실제 모델 실행 가능성의 증거가 아니다.

## Decision

- `linux-core`는 `chat=false`, `runtime_backend=none`의 정식 Static Target이다.
  Main Model Profile·GPU Image·모델 캐시·Runtime Controller를 요구하지 않는다.
- Core Gateway와 Risk Service는 기존 Static Compose·인증·Host 노출 경계를 사용한다.
  `/ready`는 Core에서 실제 필요한 Risk Dependency만 검사한다.
  `/v1/models`는 Main Model을 노출하지 않고 Chat/Responses는 `MODEL_UNAVAILABLE`로 거부한다.
- `linux-cpu-static`은 외부 CPU-only llama.cpp 서버에 Gateway를 연결한다.
  모델 가중치·엔진 버전·리소스 적합성·Runtime 감독은 외부 운영자가 소유한다.
  실환경 검증 전 CPU 프로필은 `qualification=unverified`다.
- `linux-cpu-managed`는 `managed_cpu`의 별도 Lifecycle 경계에서 플랫폼
  Compose가 CPU llama.cpp Server를 소유한다. 정적 Gateway Routing을 재사용하되
  외부 Static Target과 관리 주체는 구분한다. Image Digest와 모델 Revision·SHA-256을
  검증하며, CPU Runtime에 Docker Socket을 노출하지 않는다.
- 기존 GPU Dynamic Target의 Main 준비, GPU Admission과 strict readiness는 유지한다.
  GPU 시작 실패를 CPU/Core 성공으로 조용히 전환하지 않는다.

## Consequences

| Positive | Negative |
|---|---|
| GPU 설치·점유와 독립적인 기본 운영 | Target 변경은 운영자의 명시적인 설정 변경 필요 |
| Gateway API에서 CPU Chat 경로 재사용 | CPU GGUF 모델과 서버 준비 및 보안은 외부 운영자 소유 |
| GPU Admission과 모델 재검증 계약 보존 | 모델 자동 배치·자동 Fallback은 없음 |

## Operational impact

- Core: `make up TARGET=linux-core ACCESS=local`.
- CPU: CPU-only `llama-server` 준비 후
  `make up TARGET=linux-cpu-static ACCESS=local MAIN_URL=<private-endpoint>/v1`.
- CPU Runtime 포트는 인터넷에 공개하지 않으며 모델 파일은 명시적으로 준비한다.

## Migration notes

기존 Deployment Target의 기본값·모델 검증은 그대로 유지한다.
기존 운영자 `.env`를 자동으로 변경하거나 Runtime을 퇴거시키지 않는다.

## Related

- [ADR-0020](0020-runtime-control-and-deployment-targets.md)
- [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md)
- [ADR-0038](0038-resource-aware-secondary-runtime-topology.md)
- [ADR-0050](0050-resource-scoped-serving-authority.md)
