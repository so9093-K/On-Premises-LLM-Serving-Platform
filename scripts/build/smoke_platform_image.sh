#!/usr/bin/env bash
# Platform image가 실제 HTTP surface를 제공하는지 확인한다.
#
# app factory import만으로는 package-data에서 빠진 Console asset이나 문서 번들,
# uvicorn 기동 실패를 잡지 못한다. 이 smoke는 image의 기본 CMD로 Gateway를 띄우고
# /health, same-origin Control Plane Console과 그 asset, 문서 화면 번들을 HTTP로 받는다.
# 배포 .env는 실행 시 주입되므로 catalog의 digest 형식 해석에는 고정 fixture를 쓴다.
set -euo pipefail

IMAGE="${1:?usage: smoke_platform_image.sh <image> [platform]}"
TARGET_PLATFORM="${2:-}"
SMOKE_VLLM_IMAGE="registry.example.com/vllm-unified@sha256:0000000000000000000000000000000000000000000000000000000000000000"
HEALTH_TIMEOUT_SECONDS="${PLATFORM_SMOKE_TIMEOUT_SECONDS:-60}"

run_args=(
  --env "VLLM_IMAGE=${SMOKE_VLLM_IMAGE}"
  --env "MAIN_MODEL_VLLM_IMAGE_OVERRIDE=${SMOKE_VLLM_IMAGE}"
)
if [[ -n "$TARGET_PLATFORM" ]]; then
  run_args+=(--platform "$TARGET_PLATFORM")
fi

echo "[image] verifying platform image app factories"
docker run --rm "${run_args[@]}" --entrypoint python "$IMAGE" -c \
  "from ai_model_serving.apps.gateway import create_gateway_app; from ai_model_serving.apps.risk_signal_service import create_risk_signal_service_app; from ai_model_serving.apps.mlx_metrics_exporter import app as mlx_metrics_app; create_gateway_app(); create_risk_signal_service_app(); assert mlx_metrics_app is not None"

echo "[image] verifying Gateway HTTP surface"
container="$(docker run --detach "${run_args[@]}" --publish 127.0.0.1::9400 "$IMAGE")"
cleanup() {
  docker rm --force "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "[image] HTTP smoke failed: $*" >&2
  docker logs --tail 50 "$container" >&2 || true
  exit 1
}

port="$(docker port "$container" 9400/tcp | head -n 1 | sed 's/.*://')"
[[ -n "$port" ]] || fail "Gateway port 9400 is not published"
base="http://127.0.0.1:${port}"

deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
until curl --fail --silent --show-error --output /dev/null "${base}/health" 2>/dev/null; do
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]]; then
    fail "Gateway container exited before /health became ready"
  fi
  if (( SECONDS >= deadline )); then
    fail "/health did not answer within ${HEALTH_TIMEOUT_SECONDS}s"
  fi
  sleep 1
done

fetch() {
  curl --fail --silent --show-error "${base}$1" || fail "GET $1"
}

console_html="$(fetch /admin/console/)"
console_asset="$(printf '%s' "$console_html" | grep -o '/admin/console/assets/[^"]*\.js' | head -n 1 || true)"
[[ -n "$console_asset" ]] || fail "/admin/console/ does not reference a script asset"
fetch "$console_asset" >/dev/null

docs_html="$(fetch /docs)"
docs_asset="$(printf '%s' "$docs_html" | grep -o '/static/[^"]*\.js' | head -n 1 || true)"
[[ -n "$docs_asset" ]] || fail "/docs does not reference a self-hosted script bundle"
fetch "$docs_asset" >/dev/null

echo "[image] HTTP surface ok: /health, /admin/console/, ${console_asset}, /docs, ${docs_asset}"
