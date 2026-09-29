#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"

"$PYTHON_BIN" scripts/build/check_python.py --context test >/dev/null
# 테스트는 서로 독립적이므로 CPU 수만큼 나눠 실행한다. plugin autoload를 끄므로 xdist는
# 명시적으로 켠다. 한 process에서 순서대로 보려면 PYTEST_WORKERS=0을 준다.
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PYTHON_BIN" -m pytest -q -p xdist -n "${PYTEST_WORKERS:-auto}"
