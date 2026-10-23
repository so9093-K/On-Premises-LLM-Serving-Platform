# PR #252 — 관리형 CPU/GPU 전환 검증

> 이 문서는 당시 실행 기록이다. 아래에 언급된 기존 `tests/unit/` 테스트 파일들은 PR #277의 테스트 체계 초기화로 제거됐다. 현재 CI 테스트 범위는 [테스트·검증 실행 체계](../08_testing_validation.md)를 참고한다.

## 환경과 근거

- 2026-10-20, Ubuntu Linux x86_64, NVIDIA RTX 4090 24,564 MiB.
- 기준 Revision `7eca23b699b0d0b0195d69228ff4e8b58043d75d` 위의 PR 작업 트리.
  수정 중인 소스로 빌드한 image를 사용했으며 clean release qualification으로 해석하지 않는다.
- GPU 재시작·CPU 복구 실측 Platform image:
  `sha256:4bc33ef46f8fd3e6a38f51e39ec674dbbe4f02e3b03eeb755496dfa8b41b2c8f`.
- CPU: `Qwen/Qwen3-0.6B-GGUF`, Revision
  `1208e45d782fe18602c5eaf10e5758d5b0f24c03`, `Qwen3-0.6B-Q4_K_M.gguf`.
  SHA-256 `b0638f08417a2d3c8652760462eb5407c6e30173cf9608ad0820757a281eea0e` 검증.
- CPU image: `ghcr.io/ggml-org/llama.cpp:server-b10454@sha256:2244d2b223b49912c7e0c31b4a3654e5e62cf19899f1f36ad30e785eac171a31`.
  GPU 장치 없이 적재했으며 Adaptive CPU 제한은 RAM 4 GiB·PIDs 256이다.
- GPU: vLLM 0.30.0, `google/gemma-4-E4B-it`, Revision
  `ee0ef6023621cff504d758262d4e04895a5af4a2`, local image
  `sha256:513aa92696b33767a8c3e76a73ff644fc09d6f93801dca2fd772ec45692540d8`.
  GPU 0만 지정했으며 GPU 실행 PIDs 제한은 2,048이다.
- 기존 배포와 별도 Compose 프로젝트·Loopback 포트·상태 디렉터리를 사용했다.
  내부 제어·관측은 공유된 비공개 Bearer Token으로 인증했다. Key·내부 IP·개인 입력은 기록하지 않는다.
- 최종 CPU 재검증 image: `sha256:5cf066ef34de14f692c0922b181592681780da52c8b1c674be2eaec047e00479`.
  CPU Chat·SSE와 기존 GPU 예산 ceiling 0.93의 공개 계약을 다시 확인했다.
- 로컬 원본 요약은 `reports/validation/pr252-adaptive-runtime.json`에 기록했다.
  실행 산출물은 Git에 포함하지 않으며, 이 문서는 실제 결과의 수동 요약이다.
  모의 수치나 Benchmark 결과가 아니며 qualification 승격·CI 근거 시스템을 만들지 않는다.

## 실제 호스트에서 확인한 계약

| 시나리오 | 확인 결과 |
|---|---|
| Main·Controller 없는 Core | Gateway `/health`, Console, API 문서가 동작. 모델 목록은 비어 있고 추론 `/ready`는 503. |
| GPU 없는 독립 CPU 컨테이너 | 고정 GGUF의 적재·모델 신원·보이는 답변·SSE 종료 확인. |
| GPU 점유 상태 | 기존 별도 프로젝트가 GPU를 점유하여 여유 약 4 GiB일 때 CPU 유지. 다른 프로젝트를 퇴거하지 않음. |
| GPU 적재 검증 실패 | Healthcheck 불가 상태에서 Gate 차단·기존 CPU 재생성·Canary 성공 후 요청 복구 확인. |
| 운영자 중지 | Gateway Plan/Apply로 Main 중지. Controller 재시작 후에도 중지·Gate 차단 유지. 시작 Plan/Apply 후 CPU 검증 성공. |
| CPU→GPU 자동 복귀 | 연속 GPU 관측 후 실제 E4B 적재·텍스트와 미디어 Canary·상태 Commit 성공. |
| 전환 중 SSE 보호 | 아래 상세 실험에서 기존 스트림 종료 전 컨테이너가 유지되고 신규 요청만 503으로 거부됨. |
| GPU 상태에서 Controller 재시작 | GPU 재검증 후 Gate 개방. 자기 모델이 사용한 VRAM을 새 Admission 요구량으로 오인하여 CPU로 내리지 않음. |
| GPU 관측 장애→CPU 복구 | resource-observer를 중지하여 실제 관측 실패 재현. 약 17.6초 뒤 CPU 검증·Gate 개방. 관측 중 Core `/health`는 모두 200. |
| 복구 후 API | CPU와 GPU 각각 Chat·SSE 200, 보이는 `OK`, finish=`stop`, `[DONE]`, usage 확인. `/ready` 200. |
| 공개 계약 | 모델 목록·Main 상태·Profile 목록·Serving Envelope·Runtime 목록을 실제 API 응답으로 JSON Schema 검증. |

GPU 실측 때는 기존 Main을 Gateway의 Plan/Apply 절차로 잠시 중지했고 실험 뒤 같은
절차로 복구했다. 기존 `.env`의 Target·접근 정책·키는 이 검증을 위해 변경하지 않았다.

### SSE Drain 실험

합성 입력으로 CPU에서 256-token 한도의 SSE 요청을 실행했다. 전환과 요청이 겹치도록
테스트 컨테이너 CPU quota를 처음 0.1 CPU로 제한했다. Drain 확인 뒤 2 CPU로 올려
90초 Drain 제한 안에 정상 종료하도록 했다. 이 제약 조건의 시간·토큰 수를 성능으로 비교하면 안 된다.

- Gate 차단 당시 요청은 진행 중이었고 같은 CPU 컨테이너가 유지됐다.
- 신규 요청: HTTP 503, `MAIN_MODEL_SWITCH_IN_PROGRESS`.
- 기존 요청: HTTP 200, 이벤트 258개, 표시된 답변 338자, finish=`length`, `[DONE]`.
- Gate 차단 뒤 약 65.5초 후 스트림 완료. 이후 GPU 컨테이너 교체·Canary·Commit 확인.

## 결정론적 회귀 검증

기본 CI 경로인 `tests/unit/`에서 다음 계약을 검증한다.

- CPU Bootstrap, 장치별 GPU Admission, 안정 관측·최소 체류 시간, 메모리 압력에 따른 CPU 복구.
- 관측 오류·오래된 관측·여러 GPU의 부족한 여유 합산 금지.
- GPU Canary 실패 시 CPU Rollback과 재시작을 넘는 재시도 유예.
- Drain 실패 시 기존 엔진 보존, 엄격한 중지의 강제 종료 금지, 운영자 중지 의도 영속화.
- GPU image 설정 유실 후 CPU 복구, 내부 인증과 다른 service 제어 거부.
- CPU/GPU별 Entrypoint·환경·DeviceRequests·RAM·PIDs 교체와 기존 Mount 유지.
- 관리형 CPU·GPU 준비 실패보다 먼저 Core를 기동하는 Lifecycle 순서.
- 활성 엔진의 입력·출력 한도·Serving Envelope와 Gate에 따른 모델 목록·Readiness.

`make check`는 Python/Schema/설정·생성물과 Console 타입·안전성·산출물 일치를 검사한다.
개별 CI 실행 결과는 PR의 GitHub Checks가 소유한다.

## 해석 한계

단일 호스트의 기능·실패 복구 실험이다. 다른 GPU, 여러 Gateway Replica, 장시간 부하,
긴 문맥과 모든 모델 조합의 Qualification을 뜻하지 않는다. `qualification=unverified`를
유지한다. CPU와 GPU는 모델·지원 입력·한도가 다르며, 전환 중 새 요청은 일시 거부된다.
VRAM 계산만으로 모델 적재 성공이나 다른 프로세스와의 미래 경합 부재를 보장하지 않는다.

## 2026-10-20 후속 회귀와 RTX 6000 Ada 준비

기준 `6db55cba95afef51d753d245a16fb39496a481fd` 뒤의 변경은 아래 결정론적 테스트로
검증한다. 이 절의 메모리 압력·CPU 실패·48GB GPU 관측은 Fake Backend/합성 입력이다.
위에 기록한 기존 4090 실측과 구분하며 **RTX 6000 Ada의 적재·추론 테스트는 수행하지 않았다.**

- GPU 정상→여유 감소→CPU RAM Admission/Artifact 실패→기존 GPU·인스턴스 보존과 Gate 차단.
  압력 중 Canary 재개방 금지, 압력 해소 후 연속 정상 관측·같은 GPU Canary로 Gate 복구.
  CPU 재시도 시각이 아직 남아 있어도 GPU 복구를 막지 않는다.
- 실제 엔진 비정상과 보수적 메모리 압력을 별도 사유로 유지한다. 여유 회복만으로 엔진
  장애가 치유됐다고 간주하지 않으며 Canary 실패 시 Gate를 닫아 둔다.
- 합성 24GB/48GB 관측에서 기존 Override/Reference command를 선택한다. 점유된 48GB는
  Reference 후보를 유지하고 Admission을 차단한다. 제품명은 허용 목록으로 쓰지 않는다.
- UUID·Compute Capability 유실과 하한 미달·Artifact/정책 오류를 구분한다. 여러 GPU의
  여유·연속 관측을 합산하지 않는다. 명시적 운영자 선택을 자동 정책보다 우선한다.
- 실행 직전 같은 UUID·정책을 재확인한다. 숫자 인덱스 변경은 UUID 할당을 바꾸지 않으며
  같은 인덱스의 다른 UUID는 거부한다. 재시작 시 저장된 Variant를 먼저 복원한다.
- 초기화/재검증 Canary 뒤에도 최신 관측과 할당 UUID·압력 조건을 검사한다. command의
  리소스 인자까지 일치해야 같은 Adaptive GPU Profile로 식별한다.

테스트 원본은 `tests/unit/test_adaptive_runtime.py`, `test_adaptive_gpu_policies.py`,
`test_docker_main_model_backend.py`다. 실장비를 사용할 때의 절차와 미검증 범위는
[GPU Host 준비](../guides/gpu-host-preparation.md)에 정리했다.
