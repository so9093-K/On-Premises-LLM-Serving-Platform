# 관리형 Linux 실행 정책

## 목표와 사전 조건

Linux에서 GPU 사용 조건을 확인하고, 사용할 수 없으면 Core와 CPU 모델로 서비스를 유지합니다.
Python 3.12–3.13·uv·Docker와 모델 다운로드에 필요한 네트워크·디스크가 필요합니다.
CPU는 최소 4 GiB 여유 RAM을 요구합니다. GPU 실행에는 NVIDIA Driver·Container Toolkit,
고정 Gemma 모델에 대한 접근 권한과 충분한 장치별 VRAM이 필요합니다.

## 첫 실행

```bash
make up TARGET=auto ACCESS=local
# 처음부터 CPU 고정으로 시작하려면:
# make up TARGET=linux-nvidia-dynamic POLICY=cpu ACCESS=local
make status
```

`TARGET=auto`와 정책을 지정하지 않은 `linux-nvidia-dynamic`의 기본값은 **GPU 우선 · CPU 복구**입니다.
CPU부터 요청을 제공하고 GPU 사용 조건을 확인합니다. GPU가 부족하거나 준비·실행에 실패하면
CPU를 유지하며, 이후 GPU 여유가 생겨도 자동 복귀하지 않습니다.

| 실행 정책 | GPU를 사용할 수 없을 때 | CPU 사용 후 GPU 복귀 |
|---|---|---|
| GPU 우선 · CPU 복구 (`fallback`, 기본) | CPU 모델 검증 후 사용 | **GPU 다시 확인**을 검토·적용 |
| CPU 고정 (`cpu`) | CPU 모델 유지 | 전환하지 않음 |
| 자동 전환 (`automatic`, `POLICY=auto`) | CPU 모델 검증 후 사용 | 조건 회복 시 자동 시도 |
| GPU 고정 (`gpu`) | Main 요청 차단, Core 유지 | 선택한 GPU 모델만 사용 |

기존에 저장된 정책은 보존합니다. 정책이 없던 GPU 설정은 기본 CPU 복구 정책을 사용하고,
기존 CPU 프로필은 CPU 고정으로 유지합니다. 명시적 GPU 모델로 최초 설치하려면
`POLICY=gpu MODEL=<profile>`을 사용하며, 이 경우 CPU 자동 복구는 제공하지 않습니다.
**메인 모델 → 실행 정책**에서 정책과 모델·지원 입력 변경을 검토하세요.
자동 전환과 GPU 고정은 **고급 실행 정책**에서 선택합니다.
정책 변경에 `.env` 재생성이나 Target 변경은 필요하지 않습니다.
`POLICY=...`는 최초 설정용이며, 이후에는 Console에서 검토·적용합니다.

기존 `linux-adaptive`·`linux-cpu-managed`에서 공통 구성으로 이전하려면 `make down` 후
`make up TARGET=linux-nvidia-dynamic ACCESS=local`을 실행합니다. CPU 고정으로 새로 시작하는 경우 `POLICY=cpu`를 지정합니다. 인증값·포트·캐시·Main 상태는
보존됩니다. 기존 설치에서 영속된 실행 정책은 최초 `POLICY` 인자보다 우선하므로 이전 뒤 Console에서 현재 정책을 확인하세요.
두 기존 Target은 명시적으로 이전하기 전까지 이전 기능 범위로 동작합니다.

Gateway와 로컬 Risk가 먼저 기동합니다. CPU 모델의 고정 SHA-256 검증·적재·실제 응답
검증에 성공하면 요청을 받습니다. GPU image 준비 실패는 CPU와 Core를 중지하지 않습니다.
모델 준비 실패로 `make up`이 실패해도 Core는 유지되며 로그에서 원인을 확인할 수 있습니다.
성공 기준은 `make status`의 준비 상태와 `/v1/models`의 `local-main`입니다.

## 선택 상태 확인

Console `http://127.0.0.1:9400/admin/console/`의 **메인 모델 → 실행 정책**에서
현재 엔진과 선택 이유를 확인합니다. 같은 정보는 `/admin/main-model`의 `runtime_selection`,
실제 활성 한도는 `/admin/serving-envelope`와 `/v1/models`에서 조회합니다.
인증은 선택한 Access Profile의 관리자/API Key를 사용합니다.

| 표시 | 의미와 조치 |
|---|---|
| GPU 여유 메모리 부족 · CPU 사용 | 다른 작업을 강제 종료하지 않습니다. 기본 정책에서는 GPU 재확인을 직접 선택합니다. |
| GPU 관측 불가 · CPU 사용 | Driver·Toolkit과 resource-observer 로그를 확인합니다. |
| GPU 이미지 준비 필요 · CPU 사용 | GPU image 고정값과 빌드 로그를 확인하고 `make up`을 재실행합니다. |
| GPU 적재 및 응답 검증 중 | 새 요청은 503입니다. 기존 요청을 Drain한 뒤 실제 모델 응답을 검증합니다. |
| CPU 사용 · GPU 복귀는 수동 | **GPU 다시 확인**에서 후보 모델·입력 변화·자원을 검토합니다. |
| GPU 이미지와 드라이버 호환 조건 미충족 | 실제 이미지의 CUDA 계열과 호스트 Driver를 확인합니다. 이미지 빌드만으로 호환성을 보장하지 않습니다. |
| GPU 재시도 대기 · CPU 사용 | 실패 작업 기록을 확인합니다. 자동 전환 정책은 재시도 가능 시각 전에는 다시 시도하지 않습니다. 기본 정책은 GPU 복귀를 직접 선택합니다. |
| CPU 복구 준비 실패 · 새 요청 차단 | RAM Admission·Artifact 오류를 확인합니다. 교체 전 실패이면 기존 GPU는 유지되지만 압력·장애 중 요청은 받지 않습니다. |
| GPU 안정성 확인 중 · 새 요청 차단 | 압력 해소와 엔진 정상이 연속 관측돼야 같은 GPU를 Canary 재검증합니다. |
| GPU 응답 재검증 미완료 · 새 요청 차단 | 메모리 여유만으로 요청을 재개하지 않습니다. Canary 오류와 재검증 로그를 확인합니다. |
| 운영자가 중지함 | 런타임 화면에서 Main 시작 Plan을 검토·적용해야 재개합니다. |

GPU 사용 검토는 5초 관측, 3회 연속 관측·최소 CPU 체류 30초, 장애 2회 연속 관측을 사용합니다.
CPU 복구 실패와 자동 전환 정책의 GPU 재시도 유예는 60초입니다. CPU 복구 후 수동 복귀 의도는
재시작과 반복 `make up`에서도 유지됩니다. GPU 정책은 전체 VRAM 45,000 MiB 이상에서 기존 Reference,
23,500 MiB 이상부터 그 미만에서는 기존 `rtx4090-24gb` Override를 자동 선택합니다.
실행하려면 유효한 UUID·최소 Compute Capability와
`ceil(전체 VRAM × 선택한 Profile 예약 비율) + 512 MiB` 여유가 필요합니다.
실행 중 512 MiB 미만의 잔여 VRAM은 CPU 복구 조건입니다. 이 수치는 모델 크기의
보편적 추정이나 모든 GPU의 호환성 보증이 아닙니다. 정책 원본은
[Adaptive Catalog](../../configs/adaptive_main_model_profiles.yaml)입니다.
운영자 Override 우선순위·장치 교체·재시작·48GB급 준비 절차는
[GPU Host 준비](gpu-host-preparation.md)를 확인하세요. 제품명은 실행 허용 목록이 아닙니다.

## 요청과 기능 변화

전환 준비 중에는 기존 엔진이 요청을 처리하고, 교체 전 Gate를 닫아 신규 요청에
`MAIN_MODEL_SWITCH_IN_PROGRESS`와 `Retry-After`를 반환합니다. 진행 중인 요청은
Drain을 기다립니다. Drain 실패 시 엔진을 해체하지 않습니다. 교체·Canary 실패 시
이전 엔진을 재검증하여 복구하며 양쪽 실패 시 Gate를 닫고 Core를 유지합니다.
전환은 중단 없는 동시 서빙이 아닙니다.

GPU 메모리 압력·관측 실패·실제 엔진 장애에서는 첫 관측에 새 요청을 차단합니다.
연속 실패 기준은 CPU로 교체할 시점을 정합니다. CPU RAM Admission이나 Artifact 준비가
실패하면 교체 전의 GPU 컨테이너를 유지하지만 위험 조건이 남은 동안 Gate를 다시 열지 않습니다.
실제 엔진 장애와 자원 압력은 별도 사유로 표시합니다. 압력이 해소되고 같은 GPU의 정상 상태가
연속 관측되면 CPU 재시도 유예와 독립적으로 Canary를 수행해 성공 시에만 Gate를 엽니다.
이 복구는 컨테이너 재생성이나 진행 중 요청의 재전송을 요구하지 않습니다.

CPU는 Qwen3 0.6B, 텍스트·Chat·Responses·SSE, 문맥 2,048·출력 최대 256 tokens입니다.
GPU는 Gemma E4B의 기존 Profile 정책을 따릅니다. 같은 `local-main`이라도 모델·답변·지원
파라미터가 바뀝니다. 클라이언트는 전환 후 `/v1/models`의 입력·파라미터 한도를 다시
확인하세요. 진행 중 요청을 다른 모델에 자동 재전송하거나 결과를 합치지 않습니다.
공통 관리형 구성의 Embedding·Retrieval·모델 기반 Prompt Detector와 관측 서비스는 Main 정책과
독립적으로 유지됩니다. GPU Runtime은 최초 중지 상태이며 필요할 때 런타임 화면에서 시작합니다.
Prompt Detector를 명시적으로 중지한 동안 Gateway `/ready`는 Risk 서비스의 Core `/health`를
확인합니다. Prompt 평가 전체의 준비 상태는 Risk 서비스 `/ready`와 개별 Runtime 상태로 구분합니다.
실제 사용 가능 여부는 개별 Runtime 준비와 자원 정책을 따릅니다. 이전 `linux-adaptive` 구성은
Main과 로컬 Risk만 제공합니다.

## 중지와 장애 복구

런타임 화면의 Main 중지/시작은 Plan을 먼저 확인합니다. 중지는 진행 중 요청을 기다리며
중지 의도는 Controller 재시작 후에도 유지됩니다. 시작은 선택한 정책과 현재 프로필을 검증합니다.
공통 구성에서 프로필을 직접 선택하면 해당 엔진의 고정 정책으로 전환합니다.
이전 `linux-adaptive` 구성의 수동 Profile 전환은 잠겨 있습니다.

```bash
make logs
make logs SERVICE=runtime_controller RAW=1
make up
```

Core `/health`의 성공은 추론 성공을 뜻하지 않습니다. `/ready`는 모델 적재와 Gate를
확인합니다. Main 중지 중에는 `/ready`가 503이어도 Core `/health`와 Console은 유지됩니다.
`make up`은 명시적으로 중지한 Main을 다시 켜지 않으며 중지 상태와 Core 접속 경로를 안내합니다.
[모델 운영 계약](../06_model_operations.md)과 [검증](../08_testing_validation.md)을 함께 확인하세요.

## 검증 범위

CPU/GPU 단위 상태 전환, 실제 고정 모델의 추론·복구 증거는
[PR #252 검증 기록](../resources/adaptive_runtime_validation.md)에 구분해 기록합니다.
단일 RTX 4090 결과를 다른 GPU나 장시간 운영의 Qualification으로 확장하지 않습니다.
