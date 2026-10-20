# GPU Host 준비와 자동 리소스 정책

## 목표와 검증 범위

`linux-adaptive`가 관측한 GPU와 적용할 리소스 정책을 확인하고, 장치를 바꾸거나
Controller를 재시작해도 다른 GPU·정책으로 조용히 실행되지 않도록 준비합니다.
RTX 6000 Ada 실장비 적재·추론·장애 복구는 이번 변경에서 수행하지 않았습니다.
48GB 관측과 정책 분기는 합성 입력으로 검증했으며 `qualification=unverified`를 유지합니다.

## 1. 실행 전 장치 확인

NVIDIA Driver·Container Toolkit·Docker를 준비한 Host에서 다음을 실행합니다.
이 명령은 모델을 다운로드하거나 실행하지 않습니다.

```bash
nvidia-smi --query-gpu=index,name,uuid,pci.bus_id,compute_cap,memory.total,memory.free,driver_version --format=csv,noheader,nounits
```

성공 기준은 GPU별 제품명·UUID·PCI Bus·Compute Capability·Driver와 전체/여유 VRAM이
구분되는 것입니다. `N/A`나 조회 실패를 지원 가능으로 추정하지 않습니다. Driver나
Tooling을 수정한 뒤 다시 조회하세요. 실제 UUID·내부 주소·키를 공개 이슈에 붙이지 마세요.

이름이 비슷한 **RTX A6000**과 **RTX 6000 Ada Generation**은 다른 제품입니다.
제품명은 관측 정보이며 허용 목록으로 사용하지 않습니다. 후보 판단은 실제 전체 VRAM과
Compute Capability를 사용하고, 최종 모델 준비는 고정 image·모델 Revision과 Canary로 검증합니다.
현재 최소 Compute Capability 8.0은 BF16 후보의 보수적 사전 조건이며 특정 Driver·CUDA·
커널·모델 조합의 동작 보증이 아닙니다.

## 2. 적용할 정책 확인

기준은 [Adaptive Catalog](../../configs/adaptive_main_model_profiles.yaml)이며 실제 command는
[Main Model Catalog](../../configs/main_model_profiles.yaml)의 기존 정책을 재사용합니다.
새로운 모델 ID나 장비별 Qualification을 만들지 않습니다.

| 자동 선택 입력 | 선택 정책 | E4B `max_num_batched_tokens` |
|---|---|---|
| 전체 VRAM 45,000 MiB 이상 | 기존 Reference | 50,000 |
| 전체 VRAM 23,500 MiB 이상, 45,000 MiB 미만 | 기존 `rtx4090-24gb` Override | 4,096 |
| 그 미만 또는 UUID/Capability 확인 불가 | GPU 승격 차단, CPU 유지 | 적용하지 않음 |

여유 VRAM은 선택한 정책의 **Admission**에만 사용합니다. 예를 들어 점유 중인 48GB급
장치의 여유가 부족하면 Reference 후보를 유지하고 CPU에서 기다립니다. 같은 장치를
24GB 정책으로 자동 축소하지 않습니다. 이 계산은 모델의 정확한 최대 요구량 예측이 아닙니다.
여러 GPU의 여유를 합산하지 않으며 GPU 하나만 선택합니다.

`linux-adaptive`의 운영자 설정 우선순위는 다음과 같습니다.

1. `ADAPTIVE_GPU_RESOURCE_POLICY=reference` 또는 Catalog에 선언된 Variant ID.
2. 위 값이 `auto`/빈 값이고 `MAIN_MODEL_RESOURCE_VARIANT`가 있으면 기존 명시적 Override.
3. 둘 다 명시적 Override가 없으면 실제 전체 VRAM으로 자동 선택.

```dotenv
# 자동 선택을 원하는 새 Adaptive 환경
ADAPTIVE_GPU_RESOURCE_POLICY=auto
MAIN_MODEL_RESOURCE_VARIANT=
```

기존 4090 Override를 남겨 두면 운영자의 명시적 선택으로 유지합니다. `auto`만 적는 것으로
기존 Override를 해제하지 않습니다. 잘못된 Variant는 Reference로 대체하지 않고 원인을
표시합니다. Dynamic·Static Target의 정책 선택은 이 Adaptive 전용 설정으로 변경하지 않습니다.
기존 `.env`의 Target을 바꾸기 전에 [이전 절차](adaptive-runtime.md#첫-실행)를 확인하세요.

## 3. 향후 RTX 6000 Ada 호스트 검증 순서

아래는 해당 장치를 사용할 때 수행할 절차이며 완료된 실측 기록이 아닙니다.

1. 첫 절차로 제품명·UUID·SM·Driver·전체 VRAM을 확인합니다. Artifact 접근 권한,
   고정 GPU image와 CPU 모델의 디스크·RAM 여유도 확인합니다.
2. 준비한 새 환경에서 `make up TARGET=linux-adaptive ACCESS=local`을 실행합니다.
   접근 정책 변경을 요구하면 표시된 Plan을 검토하고 `CONFIRM=access`로 적용합니다.
3. Core `/health`와 Console 접속을 확인합니다. CPU 적재·검증 중 `/ready` 503은 추론이
   아직 준비되지 않았다는 뜻입니다. CPU Chat·SSE 완료를 확인합니다.
4. **메인 모델 → 자동 CPU/GPU 선택**에서 관측된 제품명과 UUID, 후보 정책과 선택 근거를
   확인합니다. 여유가 충분하면 안정 관측·체류 시간 뒤 GPU를 적재하고 Canary를 수행합니다.
5. GPU 검증 성공 후 활성 Profile·정책·할당 UUID와 실제 Chat·SSE·지원 미디어를 확인합니다.
   `runtime_selection.gpu_assignment`는 고정된 선택, `resources`는 최신 관측입니다.
6. 별도 검증 환경에서 Controller 재시작 후 같은 UUID·정책 복원과 Canary 성공을 확인합니다.
   인덱스가 바뀌어도 UUID를 따르며 같은 인덱스의 다른 UUID로 자동 이전하지 않습니다.
7. 실패 시나리오는 다른 운영 작업을 강제 종료하지 않는 격리 환경에서 검증합니다.
   GPU 압력→CPU 복구, CPU 준비 실패 중 기존 GPU 보존·Gate 차단, 압력 해소 후 안정 관측과
   같은 GPU의 Canary 복구를 구분합니다. 실장비 실패 주입을 수행하지 않았다면 그대로 기록합니다.

GPU image 준비 실패는 Artifact 문제, 잘못된 Variant는 정책 문제, SM 미확인/하한 미달은
호환성 문제, UUID 유실/불일치는 식별 문제입니다. `make logs SERVICE=runtime_controller RAW=1`과
`runtime_selection.reason_code`를 함께 확인합니다. Core 정상 상태는 GPU 추론 성공 증거가 아닙니다.

## 4. 기존 Adaptive 상태의 이전

새 상태는 선택한 GPU UUID와 Variant를 기존 Main 상태에 함께 저장합니다. Controller는
저장된 정책을 먼저 복원해 현재 컨테이너를 식별한 뒤 최신 관측과 Canary로 Gate를 확인합니다.
운영자 설정을 변경해도 실행 중인 GPU의 정책을 소급해서 바꾸지 않습니다. 다음 CPU→GPU 선택부터
새 설정을 적용합니다.

예전 숫자 인덱스로 실행됐고 UUID 할당이 저장되지 않은 Adaptive GPU는 이전 검증을
승계하지 않습니다. Gate를 닫고 CPU 복구 뒤 새 Admission을 거쳐 UUID로 실행합니다.
상태 파일을 수동 수정해 Gate를 여는 방식으로 이전하지 마세요. CPU RAM/Artifact가
준비되지 않으면 요청 중단이 길어질 수 있으므로 이전 전에 CPU 준비 조건을 확인하세요.

## 근거

- [NVIDIA GPU 사양](https://www.nvidia.com/en-us/products/workstations/rtx-6000/): RTX 6000 Ada의 48GB 제품 정보.
- [CUDA GPU 목록](https://developer.nvidia.com/cuda/gpus): 제품별 Compute Capability.
- [NVIDIA System Management Interface](https://docs.nvidia.com/deploy/nvidia-smi/index.html): 관측 필드와 재부팅 뒤 식별에 UUID/PCI 사용 권고.
- [Container Toolkit GPU 선택](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html): UUID 기반 GPU 선택과 `utility` 권한.
- [검증 기록](../resources/adaptive_runtime_validation.md): 기존 4090 실측과 이번 합성 회귀 검증의 경계.
