# GPU Dynamic 수동 CPU 선택 검증

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

단위 검증의 Fake Backend와 실추론 결과를 구분한다. GPU 모델 왕복 실측, 장시간 부하와
RTX 6000 Ada 실장비 검증은 이 기록에 포함되지 않는다.
