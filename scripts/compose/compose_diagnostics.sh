#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-ops/compose/full-stack.private-network.yaml}"
ENV_FILE="${ENV_FILE:-.env}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"
source scripts/lib/compose_context.sh
compose_context_init "$ROOT"
TAIL_LINES="${COMPOSE_DIAGNOSTIC_TAIL_LINES:-120}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIAGNOSTIC_DIR="${COMPOSE_DIAGNOSTIC_DIR:-$ROOT/.runtime/diagnostics/${STAMP}}"
mkdir -p "$DIAGNOSTIC_DIR"
GPU_AVOID_ABOVE="$("$PYTHON_BIN" - <<'PY' 2>/dev/null || echo "configs/gpu_budgets.yaml avoid_above"
from pathlib import Path
import yaml
doc = yaml.safe_load(Path("configs/gpu_budgets.yaml").read_text(encoding="utf-8"))
print(doc["gpu"]["total_gpu_memory_utilization"]["avoid_above"])
PY
)"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[diagnostics] Docker Compose unavailable; no Compose evidence collected" >&2
  exit 0
fi

compose_context_run ps >"$DIAGNOSTIC_DIR/compose-ps.txt" 2>&1 || true
services=(gateway runtime-controller risk-signal-service main-llm-vllm embedding-vllm embedding-ko-vllm prompt-injection-detector-runtime prometheus grafana dcgm-exporter cadvisor loki alloy)
summary_count=0

report_pattern() {
  local service="$1" pattern="$2" message="$3" file="$4"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ! ${service}: ${message}"
    summary_count=$((summary_count + 1))
  fi
}

echo "[diagnostics] Summary"
for service in "${services[@]}"; do
  service_log="$DIAGNOSTIC_DIR/${service}.log"
  compose_context_run logs --tail="$TAIL_LINES" "$service" >"$service_log" 2>&1 || true
  report_pattern "$service" "max_num_batched_tokens .* is smaller than max_model_len" "invalid vLLM batching config" "$service_log"
  report_pattern "$service" "hidden size .* is not a multiple of the number of attention heads" "Transformers/LlamaConfig compatibility failure" "$service_log"
  report_pattern "$service" "No available memory for the cache blocks" "KV-cache memory allocation failure" "$service_log"
  report_pattern "$service" "kv-cache is not supported with fp8 checkpoints" "unsupported FP8 KV-cache configuration" "$service_log"
  report_pattern "$service" "Engine core initialization failed" "vLLM engine initialization failed; inspect GPU memory and runtime policy (budget avoid_above=${GPU_AVOID_ABOVE})" "$service_log"
  report_pattern "$service" "executable file not found" "container entrypoint executable error" "$service_log"
done

if grep -E "unhealthy|Exited|Restarting|Dead" "$DIAGNOSTIC_DIR/compose-ps.txt" >"$DIAGNOSTIC_DIR/unhealthy-services.txt" 2>/dev/null; then
  echo "  ! service state: one or more containers are unhealthy/exited/restarting"
  sed 's/^/    /' "$DIAGNOSTIC_DIR/unhealthy-services.txt"
  summary_count=$((summary_count + 1))
fi
if [[ "$summary_count" -eq 0 ]]; then
  echo "  No known fatal pattern was classified. Inspect the saved evidence if the failure persists."
fi
echo "[diagnostics] Full evidence: ${DIAGNOSTIC_DIR#$ROOT/}"

if [[ "${COMPOSE_DIAGNOSTIC_VERBOSE:-0}" == "1" ]]; then
  cat "$DIAGNOSTIC_DIR/compose-ps.txt"
  for service in "${services[@]}"; do
    echo ""
    echo "== ${service} =="
    cat "$DIAGNOSTIC_DIR/${service}.log"
  done
fi
