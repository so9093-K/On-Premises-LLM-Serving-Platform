#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  "$PYTHON_BIN" scripts/runtime/macos_mlx_runtime.py stop
fi
bash scripts/ops/down_services.sh --local

app_only=0
if [[ -f "$ROOT/.env" ]] && grep -Eq '^BUILD_PROFILE=local$' "$ROOT/.env"; then app_only=1; fi
if ! command -v docker >/dev/null 2>&1; then
  if [[ "$app_only" == "1" ]]; then exit 0; fi
  echo "[down-all] Docker CLI unavailable; host processes stopped, Compose ownership cannot be checked" >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  if [[ "$app_only" == "1" ]]; then exit 0; fi
  echo "[down-all] Docker daemon unavailable; host processes stopped, Compose resources were not changed" >&2
  exit 2
fi

"$PYTHON_BIN" scripts/ops/compose_ownership.py down
