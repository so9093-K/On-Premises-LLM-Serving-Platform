#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

SCOPE="${PURGE_SCOPE:-all}"
CONFIRMED=0
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --scope)
      SCOPE="${2:-}"
      shift 2
      ;;
    --confirm)
      [[ "${2:-}" == "purge" ]] || { echo "[purge] confirmation must be exactly purge" >&2; exit 2; }
      CONFIRMED=1
      shift 2
      ;;
    *)
      echo "usage: $0 [--scope cache|all] [--confirm purge]" >&2
      exit 2
      ;;
  esac
done
case "$SCOPE" in
  cache|all) ;;
  *) echo "[purge] scope must be cache or all" >&2; exit 2 ;;
esac

print_plan() {
  echo "[purge] project-owned purge plan (scope=${SCOPE})"
  echo "  stop/remove: host processes and Compose containers/networks owned by this checkout"
  echo "  remove cache: project-built images and repository-local model caches"
  echo "  remove cache: build/test artifacts and operator diagnostic logs"
  echo "  remove volumes: Docker volumes with this checkout ownership label"
  if [[ "$SCOPE" == "all" ]]; then
    echo "  remove state: .env, .venv, .runtime and other reset-owned local state"
  else
    echo "  preserve state: .env, .venv and runtime desired state"
  fi
  echo "  preserve always: unlabeled/foreign Docker resources, global model and BuildKit caches"
  echo ""
  echo "Nothing has been removed. Apply exactly with:"
  echo "  make purge SCOPE=${SCOPE} CONFIRM=purge"
}

if [[ "$CONFIRMED" != "1" ]]; then
  print_plan
  exit 0
fi

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "[purge] Docker daemon is required to prove project ownership before destructive cleanup" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
bash scripts/ops/down_all.sh
"$PYTHON_BIN" scripts/ops/compose_ownership.py purge-artifacts

FORCE_CLEAN_RUNNING=1 bash scripts/ops/clean_project.sh --logs
for path in "$ROOT/model_cache" "$ROOT/ops/compose/model_cache" "$ROOT/models" "$ROOT/.runtime/operator-logs" "$ROOT/.runtime/diagnostics"; do
  [[ ! -e "$path" && ! -L "$path" ]] || rm -rf "$path"
done

if [[ "$SCOPE" == "all" ]]; then
  bash scripts/ops/reset_all.sh --confirm reset
fi

echo "[purge] complete: project-owned reusable artifacts were removed; host-global caches were preserved"
