#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
print_plan() {
  cat <<'EOF'
[reset] project-local reset plan
  stop/remove: host processes and Compose containers/networks owned by this checkout
  remove files: .env, .venv, .runtime, logs, run, build/test artifacts
  uninstall: this checkout's launchd supervisor for the native MLX runtime,
             if one was installed (macOS only)
  preserve: project-built images, repository-local model cache, Docker volumes,
            daemon-wide BuildKit cache, global Hugging Face cache, registry images,
            and unrelated Docker resources

Nothing has been removed. Apply exactly with:
  make reset CONFIRM=reset
EOF
}

if [[ "$#" -ne 2 || "${1:-}" != "--confirm" || "${2:-}" != "reset" ]]; then
  print_plan
  exit 0
fi

# Do not erase local configuration when Docker resources cannot first be
# inspected and stopped. This prevents an unverifiable partial reset.
if ! command -v docker >/dev/null 2>&1; then
  echo "[reset] Docker CLI is required to verify project-owned resources before reset" >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "[reset] Docker daemon is unavailable; no reset action was started" >&2
  exit 2
fi

bash scripts/ops/down_all.sh

# launchd supervisor는 ~/Library/LaunchAgents/에 있어 .runtime 삭제로 사라지지 않는다.
# 남겨두면 KeepAlive가 방금 지운 venv와 model alias를 계속 다시 실행하려 하고, 그
# crash loop가 재부팅마다 되살아난다. 파일을 지우기 전에 등록을 해제한다.
if [[ "$(uname -s)" == "Darwin" ]]; then
  "${PYTHON_BIN:-python3}" scripts/runtime/macos_mlx_runtime.py uninstall-supervisor || \
    echo "[reset] launchd supervisor uninstall skipped" >&2
fi

FORCE_CLEAN_RUNNING=1 bash scripts/ops/clean_project.sh --logs

for path in \
  "$ROOT/.env" \
  "$ROOT/.venv" \
  "$ROOT/.runtime"; do
  if [[ -e "$path" || -L "$path" ]]; then
    echo "[reset] removing ${path#$ROOT/}"
    rm -rf "$path"
  fi
done

echo "[reset] complete; reusable project images/model cache and host-global caches were preserved"
echo "[reset] next: make up TARGET=<deployment-target>"
