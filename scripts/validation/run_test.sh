#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"

# Python 지원 버전을 확인한 뒤 pytest의 원래 실패 코드를 그대로 반환한다.
# 한 프로세스에서 순서대로 보려면 PYTEST_WORKERS=0을 사용한다.
"$PYTHON_BIN" scripts/build/check_python.py --context pytest
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PYTHON_BIN" -m pytest -q -p xdist -n "${PYTEST_WORKERS:-auto}"
