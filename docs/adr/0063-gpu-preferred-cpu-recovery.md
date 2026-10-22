# ADR-0063: GPU 우선 실행과 CPU 복구 후 수동 복귀를 기본으로 한다

## Status

Accepted. ADR-0061의 기본 정책과 정책 미지정 설치의 승계 규칙을 대체한다.

## Context

정책이 비어 있는 GPU 설정을 GPU 고정으로 해석하면 드라이버 불일치나 메모리 부족 때
준비한 CPU Runtime을 사용하지 못한다. 기존 `automatic`은 CPU 복구 뒤 GPU 자동 복귀까지
수행하므로 CPU로 안정화한 상태를 유지하려는 운영 의도와 다르다.

## Decision

1. 관리형 Linux의 기본 실행 정책은 `fallback`이다. CPU 모델과 Core를 먼저 준비하고
   GPU 관측·장치별 자원 정책·이미지/드라이버 하한·공유 예산을 검사한다. GPU 후보는
   `configs/adaptive_main_model_profiles.yaml`이 소유하며 기존 모델·자원 정책을 재사용한다.
   안정 관측·최소 CPU 체류·Drain·Canary를 통과한 GPU만 요청을 받는다.
2. GPU 자원 부족·기동 실패·실행 중 장애로 CPU를 사용하면 GPU 자동 복귀를 중단한다.
   이 의도는 Main 상태의 `runtime_selection.gpu_attempted`에 영속화하며 Controller 재시작이나
   반복 `make up`으로 초기화하지 않는다. 운영자가 Console에서 GPU 재확인을 검토·적용하면
   기존 전환 엔진이 CPU를 재검증하고 GPU 사용을 다시 한 번 판단한다. 관측·이미지 준비가
   아직 끝나지 않은 초기 상태는 CPU를 제공하면서 최초 판단을 기다린다.
3. `automatic`은 기존 CPU/GPU 자동 복구·자동 복귀, `cpu`와 `gpu`는 고정 정책을 유지한다.
   GPU 고정은 CPU로 모델을 바꾸지 않으며 호환 불가 시 Core에서 원인을 확인할 수 있다.
   Console은 자동 복귀와 GPU 고정을 고급 선택으로 제공하고 적용 전 모델·입력 변화와
   실패 시 동작을 표시한다.
4. 정책 우선순위는 영속 Main 선택, `.env`의 최초 seed, 기존 CPU 의도, 기본 `fallback`이다.
   이 판단은 `main_model/execution_policy.py`가 소유하고 CLI와 Controller가 공유한다.
   기존에 저장된 고정 정책은 보존하며 Console에서 검토·적용한다. `.env` 재생성이나
   Target 변경은 정책 변경 절차가 아니다. 최초 명시적 `MODEL` 선택은 해당 엔진 고정을 뜻한다.
   `MAIN_MODEL_PROFILE_LOCKED=true`도 명시적 모델 고정이며 CPU 복구 정책과 함께 사용하면 거부한다.
5. GPU 준비의 드라이버 검사는 실제 선택 이미지의 검증된 CUDA 라벨을 읽고 이전 이미지에서는
   `CUDA_VERSION`을 읽는다. 이름·태그·기준 빌드 설정으로 실행 중 이미지를 추측하지 않는다.
   NVIDIA의 CUDA 계열별 최소 드라이버 검사는 실행 보증이 아니며 PTX/JIT·모델 호환성은
   실제 Canary가 검증한다. CUDA 12.9 후보를 만들거나 merge해도 운영 이미지를 자동 교체하지 않는다.
6. Main 교체 권한·Gate·Drain·Rollback은 기존 Manager가 소유한다. CPU RAM·Artifact 검증에
   실패하면 준비 완료를 주장하지 않는다. 다른 GPU 작업을 종료하거나 요청을 다른 모델로
   재전송하지 않는다. Core 생존과 Main 준비 상태는 독립적이다.

## Consequences

`local-main`의 실제 모델과 지원 입력은 CPU/GPU에 따라 다르므로 전환 전 검토와
전환 후 `/v1/models` 계약 확인이 필요하다. 기본 정책은 GPU가 나중에 비어도 CPU를 유지한다.
자동 복귀가 필요한 운영자는 명시적으로 `automatic`을 선택한다. 외부 Runtime과 macOS의
생명주기·실행 정책은 각 기존 소유자가 유지한다.

## Related

- [관리형 Linux 실행 정책](../guides/adaptive-runtime.md)
- [NVIDIA CUDA minor compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)
