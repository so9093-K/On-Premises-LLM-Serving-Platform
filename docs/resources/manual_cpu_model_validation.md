# GPU Dynamic 수동 CPU 선택 검증

> **현행 설정과 구분:** 아래 2026-10-21 검증은 당시의 CPU 문맥 2,048 / 최대 출력 256 정책에 대한 결과입니다. PR #278에서 기본 CPU 프로필을 8,192 / 4,096으로 변경했으며, 4K·8K·16K 프리셋은 아직 이 문서의 실장비 결과로 검증되지 않아 현재 설정에서 `unverified`로 선언합니다. 아래 `verified`는 당시 판단을 설명하는 역사적 서술입니다.

## 범위

2026-10-20, `b99a22d5` 위 작업 트리에서 수행했다. 제품 Qualification이나 성능 측정이 아니다.
기존 4090 운영 서비스는 유지했고, 별도 프로젝트·네트워크·Loopback 임시 포트를 사용했다.
입력은 공개 합성 문장 `Reply with OK only.`이며 사용자 대화·키는 기록하지 않는다.

## 결정론적 검증

- Dynamic 전환 API에서 명시적 GPU Resource Variant가 있어도 CPU 선택을 허용한다.
  GPU 관측 실패 중 CPU 전환은 기존 GPU Admission을 요구하지 않는다.
- CPU 준비 실패 시 기존 GPU·열린 Gate를 보존한다. 성공 시 기존 Drain·Canary·Commit을
  사용하고 CPU 선택은 Main 상태 저장소를 통해 재시작 뒤에도 유지된다.
- CPU의 0 예약을 기본 GPU 예약으로 바꾸지 않는다. CPU 시작·중지 Plan은 GPU 예약을
  늘리거나 다른 GPU Runtime을 퇴거시키지 않는다. 일반 GPU 요구량 0은 여전히 거부한다.
- CPU→GPU 요청은 GPU 관측 실패 시 거부한다. 관측·예산이 허용하면 명시적 요청으로 복귀한다.
- 실제 Docker 요청 payload에서 CPU의 GPU DeviceRequests 제거, RAM/PIDs 제한, 엔진
  Entrypoint 교체, Controller 재시작 뒤 원래 GPU DeviceRequests 복원을 검사했다.
- `docker compose config`로 CPU boot override의 실제 병합 결과에 GPU 장치가 없음을 확인했다.
- Dynamic·Adaptive·Managed CPU의 공개 모델 신원·입력·한도와 Scalar 실행 모드를 확인한다.
  External CPU에서는 관리형 Qwen 신원을 표시하지 않도록 검증한다.

## 격리 CPU 실추론

실제 GPU 모델을 실행한 컨테이너 대신, 별도 sleep 템플릿에 새 Backend의 CPU 교체 경로를
적용했다. 따라서 아래 결과는 실제 GPU→CPU→GPU 전환 실측이라고 해석하지 않는다.

- 기존 manifest의 Qwen3 0.6B Q4_K_M GGUF SHA-256을 재검증했다.
- image: 기존 고정 llama.cpp `server-b10454` manifest Digest.
- CPU 생성 뒤 실제 Docker inspect: GPU DeviceRequests 없음, RAM 4 GiB, PIDs 256.
- `/v1/models`: `local-main` 및 적재 완료 `meta` 확인.
- Chat HTTP 200, 보이는 응답 `OK` 확인.
- SSE HTTP 200, `[DONE]`·usage 확인.
- 검증 컨테이너·네트워크를 종료·정리했다. 운영 Gateway `/ready` 200을 확인했다.

단위 검증의 Fake Backend와 위 격리 CPU 실추론 결과를 구분한다. 후속 Dynamic 왕복 실측은 아래에 별도로 기록한다.


## 실제 Dynamic API의 GPU→CPU→GPU 왕복

코드 Revision `38d8582a`의 clean Platform image를 현재 Linux/RTX 4090 환경에 반영했다.
실제 전환은 Gateway의 관리자 API로 요청했고 기존 Main 전환 엔진이 처리했다.
기존 GPU는 Plan/Apply·Drain으로 중지한 뒤 새 image와 CPU cache mount를 반영했다.

| 단계 | 실제 확인 |
|---|---|
| GPU→CPU 수동 요청 | `cpu-gguf-text` 전환 completed, 약 8.1초 |
| CPU 공개 정보 | `Qwen/Qwen3-0.6B-GGUF`, `llama-cpp`, 문맥 2,048 / 최대 출력 256 |
| CPU Docker 제한 | GPU DeviceRequests 없음, RAM 4 GiB |
| CPU 추론 | Chat 200·보이는 `OK`, SSE 종료·usage 확인 |
| CPU→GPU 수동 요청 | `gemma4-e4b-it` 전환 completed, 약 117.4초 |
| GPU 공개 정보 | `google/gemma-4-E4B-it`, `vllm-cuda`, 문맥 65,000 / 최대 출력 15,000 |
| GPU 복구 뒤 추론 | Chat 200·보이는 `OK`, SSE 종료·usage, `/ready` 200 |

이 시간은 모델 교체·적재·검증을 포함한 한 번의 전환 소요이며 성능 Benchmark가 아니다.
CPU에서 GPU로 복귀한 요청도 운영자가 명시적으로 보냈다. 자동 선택 실험이 아니다.
Controller 재시작 뒤 GPU 장치 복원은 별도 결정론적 Backend 테스트에서 확인했다.

`reports/validation/manual-cpu-dynamic-roundtrip.json`에 실제 image ID와 결과 요약을
로컬로 보존한다. 실행 산출물은 Git에 포함하지 않는다. `.env`의 배포 Target·접근/인증은
유지했으며 로컬 재빌드에 따라 VLLM image pin 두 항목을 갱신했다.

재기동 중 Gateway가 Main health를 기다리는 기존 Compose 의존성을 확인했다.
이 의존성을 제거하고 실제 Compose 병합 검사로 Gateway 기동이 Main에 종속되지 않도록
검증했다. Core만 다시 적용해 운영 UI 접근과 기존 GPU 추론 준비 상태를 확인했다.

이 시점에는 단일 RTX 4090 호스트의 기능 검증으로 기록하고 CPU 프로필의 `unverified`를 유지했다.
장시간 부하·모든 오류 주입과 RTX 6000 Ada 실장비 검증을 뜻하지 않는다.

## CPU 프로필 Qualification — 2026-10-21

`494fd74a` 기반 변경을 Linux x86_64 / AMD Ryzen 9 7900X3D에서 검증했다.
모델·GGUF 무결성은 `configs/cpu_model_artifact.yaml`, 엔진은 고정 llama.cpp
`server-b10454` Digest를 사용했다.

- 실제 Gateway API로 GPU→Qwen CPU 전환 완료, 고정 revision과 Gate open 확인.
- Docker inspect: GPU DeviceRequests 없음, RAM 4 GiB, PIDs 256.
- `make cpu-runtime-validate` 통과: CPU Backend·모델 ID·텍스트 입력·문맥 2,048·최대 출력
  256 일치, Chat 응답 및 SSE 응답·종료 이벤트·`[DONE]` 확인.
- 기존 GPU `gemma4-e4b-it` 복귀 완료, Runtime ready·Gate open·Gateway `/ready` 200.

공통 CPU 프로필을 `compatible` / `verified`로 선언한다. Deployment Target의
Qualification은 별개로 유지한다. 실행 요약은 로컬
`reports/validation/qwen-cpu-qualification.json`에 보존한다.
