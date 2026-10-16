# 통합 vLLM Runtime 이미지 — 빌드와 활성화

Main Model의 26B·12B Profile, Embedding, Embedding-KO, Risk-Prompt는
하나의 파생 vLLM 이미지(통합 Runtime Artifact)를 사용한다.
과거 별도 이미지 `vllm-gemma4-audio`(12B 멀티모달)와
`risk-vllm-kanana`(Kanana Risk-Prompt)를 대체한다.
두 Patch 집합이 서로 다른 파일을 변경하는 것을 확인한 후 2026-07-24에 통합했다.
자세한 적용 범위는 `Dockerfile` 머리글 주석을 참고한다.

서로 독립된 세 Patch 집합을 적용하며, 해당하지 않는 모델에서는 수정이 영향을 주지 않는다.

1. **Gemma4-unified 멀티모달(12B 전용)** — 기본 이미지의 `libsndfile1`,
   soundfile, librosa, PyAV로 구성한 미디어 디코딩 환경,
   `vision_embedder.patch_dense`의 FP8 오양자화 수정,
   Audio Warmup의 `fft_length` 수정. 26B는 다른 `gemma4` 아키텍처를
   사용하므로 이 코드 경로를 실행하지 않으며 통합 이미지에서도 기존과 동일하게 동작한다.
2. **Kanana Llama `head_dim` 보호(Risk-Prompt 전용)** — 명시적 Llama
   `head_dim` 호환성 Patch. 다른 Serving 모델은 명시적 `head_dim`을
   설정하지 않으므로 해당 변경의 영향을 받지 않는다.
3. **Gemma4 Streaming Parser** — Upstream의 Open-channel Reasoning 수정 여부를
   검증하고, Streaming 응답에서 사용하는 로컬 종료 기호 `<turn|>`를 처리한다.

vLLM 0.30.0은 BitsAndBytes 양자화 기능을 공식
[`vllm-bnb-plugin`](https://github.com/vllm-project/vllm-bnb-plugin)으로 분리했다.
Kanana Detector는 계속 `--quantization bitsandbytes`를 사용하므로,
파생 이미지는 `requirements.bnb.lock`의 정확한 Wheel Hash로
Plugin과 BitsAndBytes를 설치하고 빌드 중 등록 상태를 검증한다.

Patch 스크립트는 작성 당시의 Upstream 코드 구조를 엄격히 확인한다.
기준 이미지를 교체해 해당 구조가 달라지면 손상된 이미지를 조용히 배포하지 않고
빌드 단계에서 명시적으로 실패한다.

## 빌드와 활성화

네이티브 Linux amd64 Docker Daemon에서 이미지를 빌드한다.
출력 이미지 이름은 별도의 명시적 빌드 인자로 지정하며 Runtime `.env`에서는 읽지 않는다.

```bash
VLLM_UNIFIED_BUILD_IMAGE='registry.example.com/project/vllm-unified:<tag>' \
make build-vllm-unified-image
docker push registry.example.com/project/vllm-unified:<tag>
```

운영 승격은 Push 결과의 `name@sha256:...` Digest를 사용한다.
공유 Runtime의 영속 이미지 Source of Truth는 `VLLM_IMAGE`다.
Main Model의 일반 Profile, Embedding, Embedding-KO, Risk-Prompt는
여기에 지정된 검증된 Artifact를 공유한다.

Main Model Profile이 명시적으로 다른 이미지를 선택해야 할 때는
`MAIN_MODEL_VLLM_IMAGE_OVERRIDE`가 Profile 전용 Override를 소유한다.

Registry에 게시된 이미지를 사용하려면 불변 `name@sha256:...` Digest를
대상 호스트의 영속 `VLLM_IMAGE`에 명시적으로 고정한 다음
Canonical 로컬 생명주기로 수렴시킨다.
게시·전달 자동화에는 저장소 Runtime을 변경할 별도 권한이 없다.

기본 이미지와 호환성 Pin은 `configs/vllm_unified_build.yaml`에서 읽는다.
검증을 위해 기준 이미지를 교체해야 할 때에만 해당 빌드에 한정하여
불변 Digest를 명시적으로 전달한다.

vLLM 0.30.0의 공식 `-cu129` amd64 이미지에는 Torch 2.14.0+cu130과
torchvision 0.28.0+cu129가 함께 포함돼 `import torchvision`이 실패했다.
현재 기준 이미지는 실제 Import 및 GPU 접근이 확인된 CUDA 13.0 amd64 이미지다.
Dockerfile은 Torch/torchvision Import와 CUDA Variant 일치 여부를 빌드 중 검사한다.

후보 기준 이미지의 의존성 메타데이터도 확인해야 한다.
현재 CUDA 13.0 기준 이미지에서 `pip check`는 설치된 `nvidia-nccl-cu13`
버전(2.30.7)이 Torch 메타데이터의 요구 버전(2.29.7)과 다르다고 보고한다.
이 프로젝트의 단일 GPU/TP=1 Canary가 통과하더라도
**다중 GPU 호환성이 검증됐다는 근거는 아니다.**

```bash
VLLM_BASE_IMAGE='vllm/vllm-openai@sha256:<digest>' make build-vllm-unified-image
```

불변 Digest가 아닌 값(변경 가능한 태그 등)은 빌드 단계에서 거부한다.
`VLLM_BASE_IMAGE`는 Runtime `.env`에서 읽지 않는다.
`configs/env_contract.yaml`의 `removed_keys`에 등록되어
`python scripts/config/setup_env.py --sync-env --env-file .env`가 제거한다.
기준 이미지를 영속 설정에 남겨두면 오래된 값이
Canonical Digest를 계속 덮어쓸 수 있기 때문이다.

## Main Model Profile 전환과 검증

`POST /admin/main-model/switch {"profile":"gemma4-12b-unified-fp8","confirm_unverified":true}`

모델 전환 시 Backend는 Text Canary와 Audio·Video Media Boot Canary를 실행한다.
Runtime이 지원한다고 선언한 입력 형식을 실제로 디코딩하지 못하면
전환은 실패하고 Rollback한다. 12B 모델을 일부 기능만 가능한 상태로
정상 Serving하지 않는다.
