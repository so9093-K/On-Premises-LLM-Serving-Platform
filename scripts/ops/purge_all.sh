#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
source scripts/lib/project_image_ownership.sh

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
  echo "  remove volumes: Docker volumes carrying this Compose project label, when identifiable"
  if [[ "$SCOPE" == "all" ]]; then
    echo "  remove state: .env, .venv, .runtime and other reset-owned local state"
  else
    echo "  preserve state: .env, .venv and runtime desired state"
  fi
  echo "  preserve always: global Hugging Face cache, daemon-wide BuildKit cache, unrelated Docker resources"
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

projects=""
container_ids="$(docker ps -aq --filter "label=com.docker.compose.project.working_dir=${ROOT}" 2>/dev/null || true)"
for container_id in $container_ids; do
  project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$container_id" 2>/dev/null || true)"
  [[ -n "$project" ]] && projects="${projects}${project}"$'\n'
done
if [[ -f "$ROOT/.env" ]]; then
  configured_project="$(awk -F= '$1=="COMPOSE_PROJECT_NAME" {print substr($0,index($0,"=")+1); exit}' "$ROOT/.env")"
  [[ -n "$configured_project" ]] && projects="${projects}${configured_project}"$'\n'
fi
projects="$(printf '%s' "$projects" | sort -u)"

bash scripts/ops/down_all.sh

image_ids="$(
  {
    docker image ls -q --filter "label=${PROJECT_IMAGE_LABEL_KEY}=${PROJECT_IMAGE_LABEL_VALUE}"
    docker image ls -q "$PROJECT_PLATFORM_IMAGE_REPOSITORY"
    docker image ls -q "$PROJECT_VLLM_IMAGE_REPOSITORY"
  } 2>/dev/null | sort -u
)"
image_refs="$(
  {
    docker image ls --filter "label=${PROJECT_IMAGE_LABEL_KEY}=${PROJECT_IMAGE_LABEL_VALUE}" --format '{{.Repository}}:{{.Tag}}'
    docker image ls "$PROJECT_PLATFORM_IMAGE_REPOSITORY" --format '{{.Repository}}:{{.Tag}}'
    docker image ls "$PROJECT_VLLM_IMAGE_REPOSITORY" --format '{{.Repository}}:{{.Tag}}'
  } 2>/dev/null | grep -v '^<none>:' | sort -u || true
)"
if [[ -n "$image_refs" ]]; then
  docker image rm $image_refs >/dev/null
fi
for image_id in $image_ids; do
  if docker image inspect "$image_id" >/dev/null 2>&1; then
    docker image rm "$image_id" >/dev/null
  fi
done

while IFS= read -r project; do
  [[ -n "$project" ]] || continue
  volume_ids="$(docker volume ls -q --filter "label=com.docker.compose.project=${project}" 2>/dev/null || true)"
  [[ -z "$volume_ids" ]] || docker volume rm $volume_ids >/dev/null
done <<< "$projects"

FORCE_CLEAN_RUNNING=1 bash scripts/ops/clean_project.sh --logs
for path in "$ROOT/model_cache" "$ROOT/ops/compose/model_cache" "$ROOT/models" "$ROOT/.runtime/operator-logs" "$ROOT/.runtime/diagnostics"; do
  [[ ! -e "$path" && ! -L "$path" ]] || rm -rf "$path"
done

if [[ "$SCOPE" == "all" ]]; then
  bash scripts/ops/reset_all.sh --confirm reset
fi

echo "[purge] complete: project-owned reusable artifacts were removed; host-global caches were preserved"
