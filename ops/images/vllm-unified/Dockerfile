# Main Model·Embedding·Risk-Prompt가 공유하는 고정 vLLM artifact다.
# Gemma4 Unified의 멀티모달 패치, Llama head_dim 보호, Gemma4 streaming 패치는
# 서로 다른 실행 경로에 적용되며 각 스크립트가 상류 코드 구조를 검증한다.
# 기준 이미지·공통 버전·CUDA 후보는 configs/vllm_unified_build.yaml이 소유한다.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# configs/vllm_unified_build.yaml이 값을 소유하며 공통 build script가 항상 전달한다.
ARG VLLM_VERSION
ARG TRANSFORMERS_VERSION
ARG HUGGINGFACE_HUB_VERSION
ARG CUDA_VARIANT=cu130
ARG EXPECTED_CUDA_VERSION=13.0

# CUDA 12.9 후보는 상류 이미지의 혼합 의존성을 고정 lock으로 교정한다.
# LMCache는 이 플랫폼이 제공하지 않는 선택적 기능이며 CUDA 13 의존을 요구한다.
COPY ops/images/vllm-unified/requirements.cu129-pytorch.lock /usr/local/share/ai-model-serving/cu129/requirements.cu129-pytorch.lock
COPY ops/images/vllm-unified/requirements.cu129-runtime.lock /usr/local/share/ai-model-serving/cu129/requirements.cu129-runtime.lock
RUN if [ "$CUDA_VARIANT" = "cu129" ]; then \
      python3 -m pip uninstall -y lmcache \
      && python3 -m pip install --no-cache-dir --no-deps --require-hashes \
         --index-url https://download.pytorch.org/whl/cu129 \
         -r /usr/local/share/ai-model-serving/cu129/requirements.cu129-pytorch.lock \
      && python3 -m pip install --no-cache-dir --no-deps --require-hashes \
         --index-url https://pypi.org/simple \
         -r /usr/local/share/ai-model-serving/cu129/requirements.cu129-runtime.lock; \
    elif [ "$CUDA_VARIANT" != "cu130" ]; then \
      echo "Unsupported CUDA variant: $CUDA_VARIANT" >&2; exit 2; \
    fi

COPY scripts/build/verify_cuda129_image.py /usr/local/bin/verify_cuda129_image.py
RUN if [ "$CUDA_VARIANT" = "cu129" ]; then python3 /usr/local/bin/verify_cuda129_image.py; fi

LABEL org.opencontainers.image.title="ai-model-serving-vllm-unified"
LABEL org.opencontainers.image.description="Single vLLM runtime for all served models: Gemma4 multimodal fixes + Kanana Llama head_dim guard"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL ai_model_serving.patch.gemma4_multimodal="true"
LABEL ai_model_serving.patch.gemma4_streaming_reasoning="true"
LABEL ai_model_serving.patch.transformers_llama_head_dim_guard="true"
LABEL ai_model_serving.patch.reason="Kanana explicit head_dim compatibility"
LABEL ai_model_serving.patch.remove_when="Upstream Transformers/vLLM honors explicit Llama head_dim without image patch"
LABEL ai_model_serving.patch.metadata_path="/usr/local/share/ai-model-serving/patches/transformers_llama_head_dim_guard.json"
LABEL ai_model_serving.vllm_version="${VLLM_VERSION}"
LABEL ai_model_serving.transformers_version="${TRANSFORMERS_VERSION}"
LABEL ai_model_serving.huggingface_hub_version="${HUGGINGFACE_HUB_VERSION}"

# ── Gemma4-unified multimodal: media decode stack ──────────────────────────
# The pinned upstream base already includes libsndfile1, the native backend
# soundfile binds to.  Verify it locally rather than running apt-get update:
# re-fetching mutable Ubuntu/PPA metadata makes a derived-image rebuild depend
# on CI network state without changing the resulting dependency.
RUN dpkg-query -W -f='libsndfile1=${Version}\n' libsndfile1

COPY ops/images/vllm-unified/requirements.media.lock /tmp/requirements.media.lock
RUN python3 -m pip install --no-cache-dir --no-deps --requirement /tmp/requirements.media.lock \
    && rm /tmp/requirements.media.lock

RUN python3 -c "import av, soundfile, librosa; print('media decode ok', soundfile.__version__, librosa.__version__, av.__version__)"

# vLLM 0.30.0 moved BitsAndBytes support to its official out-of-tree plugin.
# Kanana still uses in-flight 4-bit quantization. Pin both wheels and verify
# registration, otherwise the risk-prompt service fails during engine config.
COPY ops/images/vllm-unified/requirements.bnb.lock /tmp/requirements.bnb.lock
RUN python3 -m pip install --no-cache-dir --no-deps --require-hashes \
    --requirement /tmp/requirements.bnb.lock \
    && rm /tmp/requirements.bnb.lock
RUN python3 - <<'PY'
from vllm.plugins import load_general_plugins
from vllm.model_executor.layers.quantization import get_quantization_config

load_general_plugins()
assert get_quantization_config("bitsandbytes").__name__ == "BitsAndBytesConfig"
print("vllm-bnb-plugin registration ok")
PY

# ── Gemma4-unified multimodal: image FP8 mis-quant + audio fft_length fixes ─
COPY ops/patches/apply_gemma4_multimodal_patches.py /tmp/apply_gemma4_multimodal_patches.py
RUN python3 /tmp/apply_gemma4_multimodal_patches.py \
    && rm /tmp/apply_gemma4_multimodal_patches.py

# ── Gemma4: streaming reasoning/content parser consistency ─────────────────
COPY ops/patches/apply_gemma4_streaming_reasoning_patch.py /tmp/apply_gemma4_streaming_reasoning_patch.py
RUN python3 /tmp/apply_gemma4_streaming_reasoning_patch.py \
    && rm /tmp/apply_gemma4_streaming_reasoning_patch.py

# ── Kanana risk-prompt: verified base dependency pair ───────────────────────
# 선택한 기준 이미지와 명시적인 CUDA lock이 실행 의존성을 소유한다.
RUN python3 - "$VLLM_VERSION" "$TRANSFORMERS_VERSION" "$HUGGINGFACE_HUB_VERSION" "$EXPECTED_CUDA_VERSION" <<'PY'
from __future__ import annotations

import sys

import huggingface_hub
import torch
import torchvision
import transformers
import vllm

expected_vllm, expected_transformers, expected_hub, expected_cuda = sys.argv[1:]
actual_vllm = vllm.__version__.partition("+")[0]
actual_transformers = transformers.__version__
actual_hub = huggingface_hub.__version__
torch_cuda = torch.__version__.partition("+")[2]
vision_cuda = torchvision.__version__.partition("+")[2]

if (
    actual_vllm != expected_vllm
    or actual_transformers != expected_transformers
    or actual_hub != expected_hub
):
    print(
        "vLLM base dependency mismatch: "
        f"vllm={actual_vllm} (expected {expected_vllm}), "
        f"transformers={actual_transformers} (expected {expected_transformers}), "
        f"huggingface_hub={actual_hub} (expected {expected_hub})",
        file=sys.stderr,
    )
    sys.exit(1)
if not torch_cuda or torch_cuda != vision_cuda or torch.version.cuda != expected_cuda:
    print(
        f"PyTorch/torchvision CUDA variant mismatch: torch={torch.__version__}, "
        f"torchvision={torchvision.__version__}, "
        f"cuda={torch.version.cuda} (expected {expected_cuda})",
        file=sys.stderr,
    )
    sys.exit(1)
print(
    "vllm-unified "
    f"vllm={actual_vllm} transformers={actual_transformers} "
    f"huggingface_hub={actual_hub} torch={torch.__version__} "
    f"torchvision={torchvision.__version__}"
)
PY

RUN if [ "$CUDA_VARIANT" = "cu129" ]; then python3 /usr/local/bin/verify_cuda129_image.py; fi

# ── Kanana risk-prompt: Llama head_dim guard ────────────────────────────────
COPY ops/patches/transformers_llama_head_dim_guard.py /usr/local/bin/transformers_llama_head_dim_guard.py
RUN python3 /usr/local/bin/transformers_llama_head_dim_guard.py --json \
    && python3 /usr/local/bin/transformers_llama_head_dim_guard.py --verify --json


# 문서 변경이 위의 무거운 dependency·patch layer를 무효화하지 않게 마지막에 둔다.
# Base image와 설치된 dependency는 각각의 원 라이선스를 유지한다.
RUN --mount=type=bind,target=/build-source \
    mkdir -p /usr/share/licenses/ai-model-serving-platform \
    && for file in LICENSE NOTICE; do \
         if [ -f "/build-source/$file" ]; then \
           cp "/build-source/$file" /usr/share/licenses/ai-model-serving-platform/; \
         fi; \
       done
