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

# Full-stack reset must prove Docker ownership before erasing configuration.
# App-only has no Compose lifecycle, so a host without Docker can still reset
# after its repository-owned processes are stopped.
BUILD_PROFILE=""
if [[ -f "$ROOT/.env" ]]; then
  BUILD_PROFILE="$(
    awk -F= '$1=="BUILD_PROFILE" {print substr($0,index($0,"=")+1); exit}' "$ROOT/.env"
  )"
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  bash scripts/ops/down_all.sh
elif [[ "$BUILD_PROFILE" == "local" ]]; then
  echo "[reset] Docker unavailable; stopping app-only host processes"
  bash scripts/ops/down_services.sh --local
else
  echo "[reset] Docker daemon is required to verify full-stack project ownership before reset" >&2
  exit 2
fi

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
