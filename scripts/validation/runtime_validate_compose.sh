#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python || true)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[runtime-validate] Python 3.12 or 3.13 is required to resolve the Compose context." >&2
  exit 2
fi

source scripts/lib/compose_context.sh
compose_context_init "$ROOT"
compose_context_assert_mutation_safe

if [[ ! -f "$ENV_FILE_ABS" ]]; then
  echo "[runtime-validate] env file not found: $ENV_FILE_ABS" >&2
  exit 2
fi
"$PYTHON_BIN" scripts/env/env_validate.py --env-file "$ENV_FILE_ABS"

gateway_container="$(compose_context_run ps --status running -q gateway 2>/dev/null || true)"
if [[ -z "$gateway_container" ]]; then
  echo "[runtime-validate] gateway is not running in Compose project $COMPOSE_PROJECT_NAME_EFFECTIVE." >&2
  echo "[runtime-validate] Start the platform with 'make up' before live validation." >&2
  exit 2
fi

mkdir -p reports/runtime
export RUNTIME_VALIDATOR_UID="$(id -u)"
export RUNTIME_VALIDATOR_GID="$(id -g)"

VALIDATION_COMPOSE="$ROOT/ops/compose/runtime-validation.yaml"
COMPOSE_ARGS=("${COMPOSE_CONTEXT_FILE_ARGS[@]}" -f "$VALIDATION_COMPOSE")

echo "[runtime-validate] validating through Compose internal service DNS"
docker compose "${COMPOSE_ARGS[@]}" --env-file "$ENV_FILE_ABS"   run --rm --no-deps -T runtime-validator
