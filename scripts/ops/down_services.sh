#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"

SCOPE="${1:---all}"
case "$SCOPE" in
  --local)
    stop_compose=0
    stop_local=1
    ;;
  --compose)
    stop_compose=1
    stop_local=0
    ;;
  --all)
    stop_compose=1
    stop_local=1
    ;;
  *)
    echo "usage: $0 [--local|--compose|--all]" >&2
    exit 2
    ;;
esac

if [[ "$stop_compose" == "1" ]]; then
  "$PYTHON_BIN" scripts/ops/compose_ownership.py down
fi

if [[ "$stop_local" == "1" ]]; then
  for name in gateway risk_signal_service; do
    pid_file="run/${name}.pid"
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file")"
      if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]] || (( pid <= 1 )); then
        echo "[down] invalid pid in ${pid_file}; refusing to signal a process group" >&2
        exit 2
      fi
      if kill -0 "$pid" >/dev/null 2>&1; then
        echo "[down] stopping ${name} pid ${pid}"
        kill "$pid"
        for _ in $(seq 1 120); do
          kill -0 "$pid" >/dev/null 2>&1 || break
          sleep 0.25
        done
        if kill -0 "$pid" >/dev/null 2>&1; then
          echo "[down] ${name} did not stop; pid file preserved" >&2
          exit 2
        fi
      fi
      rm -f "$pid_file"
    fi
  done
fi
