#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source scripts/lib/project_image_ownership.sh
source scripts/lib/image_ref_policy.sh

if ! command -v docker >/dev/null 2>&1; then
  echo "[vllm-unified-image] Docker CLI is required." >&2
  exit 2
fi
if ! DAEMON_PLATFORM="$(docker info --format '{{.OSType}}/{{.Architecture}}' 2>/dev/null)"; then
  echo "[vllm-unified-image] Cannot access the Docker daemon." >&2
  exit 2
fi

source scripts/lib/vllm_unified_image.sh
VERSION="$(cat VERSION)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3.13 || command -v python3 || command -v python)}"
TARGET_PLATFORM="$("$PYTHON_BIN" scripts/models/print_vllm_unified_compatibility.py --key target_platform)"
case "${TARGET_PLATFORM}:${DAEMON_PLATFORM}" in
  linux/amd64:linux/x86_64|linux/amd64:linux/amd64) ;;
  *)
    echo "[vllm-unified-image] Docker daemon ${DAEMON_PLATFORM} cannot provide the required native target ${TARGET_PLATFORM}." >&2
    echo "[vllm-unified-image] Build this CUDA image on the Ubuntu/Linux amd64 build path; macOS Metal is a separate runtime target." >&2
    exit 2
    ;;
esac

IMAGE="${VLLM_UNIFIED_BUILD_IMAGE:-$(vllm_unified_default_image)}"
EXTRA_TAGS="${VLLM_UNIFIED_BUILD_EXTRA_TAGS:-}"
BASE_IMAGE="${VLLM_BASE_IMAGE:-$(vllm_unified_canonical_base_image)}"
if ! require_registry_digest_image_ref "VLLM_BASE_IMAGE" "${BASE_IMAGE}"; then
  exit 2
fi
CACHE_FROM="${VLLM_UNIFIED_BUILD_CACHE_FROM:-}"
PULL_BASE_IMAGE="${VLLM_UNIFIED_BUILD_PULL_BASE:-0}"
PROJECT_BUILD_NO_CACHE="${PROJECT_BUILD_NO_CACHE:-0}"
VLLM_VERSION="$("$PYTHON_BIN" scripts/models/print_vllm_unified_compatibility.py --key vllm)"
TRANSFORMERS_VERSION="$("$PYTHON_BIN" scripts/models/print_vllm_unified_compatibility.py --key transformers)"
HUGGINGFACE_HUB_VERSION="$("$PYTHON_BIN" scripts/models/print_vllm_unified_compatibility.py --key huggingface_hub)"
source scripts/lib/source_provenance.sh
read_source_provenance vllm-unified

echo "[vllm-unified-image] building ${IMAGE}"
echo "[vllm-unified-image] source=${SOURCE_STATE} digest=${SOURCE_DIGEST} target=${TARGET_PLATFORM}"
if [[ -n "$SOURCE_REVISION" ]]; then
  echo "[vllm-unified-image] revision=${SOURCE_REVISION}"
fi
echo "[vllm-unified-image] base=${BASE_IMAGE} vllm=${VLLM_VERSION} transformers=${TRANSFORMERS_VERSION} huggingface_hub=${HUGGINGFACE_HUB_VERSION}"

if [[ "$PULL_BASE_IMAGE" == "1" ]]; then
  echo "[vllm-unified-image] pulling base image"
  docker pull --platform "$TARGET_PLATFORM" "$BASE_IMAGE"
fi

build_args=(
  --platform "$TARGET_PLATFORM"
  --file ops/images/vllm-unified/Dockerfile
  --build-arg "BASE_IMAGE=${BASE_IMAGE}"
  --build-arg "VLLM_VERSION=${VLLM_VERSION}"
  --build-arg "TRANSFORMERS_VERSION=${TRANSFORMERS_VERSION}"
  --build-arg "HUGGINGFACE_HUB_VERSION=${HUGGINGFACE_HUB_VERSION}"
  --label "org.opencontainers.image.revision=${SOURCE_REVISION}"
  --label "org.opencontainers.image.version=${VERSION}"
  --label "ai_model_serving.source_state=${SOURCE_STATE}"
  --label "ai_model_serving.source_digest=${SOURCE_DIGEST}"
  --label "ai_model_serving.runtime_digest=${SOURCE_RUNTIME_DIGEST}"
  --label "ai_model_serving.build_platform=${TARGET_PLATFORM}"
  --label "ai_model_serving.vllm_version=${VLLM_VERSION}"
  --label "${PROJECT_IMAGE_LABEL_KEY}=${PROJECT_IMAGE_LABEL_VALUE}"
  --label "${PROJECT_CHECKOUT_LABEL_KEY}=$(pwd -P)"
  --label "ai_model_serving.artifact=vllm-unified"
)
if [[ "$PROJECT_BUILD_NO_CACHE" == "1" ]]; then
  build_args+=(--no-cache)
fi
if [[ -n "$CACHE_FROM" ]]; then
  build_args+=(--cache-from "$CACHE_FROM")
fi
build_args+=(--tag "$IMAGE")
for tag in $EXTRA_TAGS; do
  build_args+=(--tag "$tag")
done

docker build "${build_args[@]}" .
echo "[vllm-unified-image] built ${IMAGE}"
