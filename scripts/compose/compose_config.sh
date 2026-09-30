#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"
source scripts/lib/compose_context.sh
compose_context_init "$ROOT"

"$PYTHON_BIN" scripts/env/env_validate.py --env-file "$ENV_FILE_ABS"

BOOT_OVERRIDE="$(mktemp "${TMPDIR:-/tmp}/main-model-boot.XXXXXX.yaml")"
trap 'rm -f "$BOOT_OVERRIDE"' EXIT
"$PYTHON_BIN" scripts/models/render_main_model_boot_override.py \
  --env-file "$ENV_FILE_ABS" \
  --output "$BOOT_OVERRIDE" >/dev/null

COMPOSE_ARGS=("${COMPOSE_CONTEXT_FILE_ARGS[@]}" -f "$BOOT_OVERRIDE")
docker compose "${COMPOSE_ARGS[@]}" --env-file "$ENV_FILE_ABS" config
