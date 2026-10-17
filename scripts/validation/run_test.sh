#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"

# Python 호환성 검사와 xdist 실행 정책은 공통 검증 CLI가 소유한다.
# 한 process에서 순서대로 보려면 PYTEST_WORKERS=0을 준다.
"$PYTHON_BIN" scripts/validation/run_suite.py pytest
