#!/usr/bin/env bash

# 공유되는 Docker Compose 실행 컨텍스트를 확정합니다.
#
# 우선순위:
#   프로세스 COMPOSE_PROJECT_NAME
#   -> ENV_FILE COMPOSE_PROJECT_NAME
#   -> ai-model-serving-platform
#
# 호출하는 쪽에서는 target/runtime boot처럼 실제로 필요한 추가 Compose 파일을
# COMPOSE_CONTEXT_FILE_ARGS에 명시적으로 추가할 수 있습니다.
compose_context_init() {
  local root="${1:?project root required}"
  local python_bin="${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}"
  local project_name="${COMPOSE_PROJECT_NAME:-}"

  ENV_FILE="${ENV_FILE:-.env}"
  COMPOSE_FILE="${COMPOSE_FILE:-ops/compose/full-stack.private-network.yaml}"
  ENV_FILE_ABS="$("$python_bin" -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$ENV_FILE")"
  COMPOSE_FILE_ABS="$("$python_bin" -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$COMPOSE_FILE")"

  if [[ -z "$project_name" && -f "$ENV_FILE_ABS" ]]; then
    project_name="$(
      "$python_bin" "$root/scripts/env/env_get.py" \
        --env-file "$ENV_FILE_ABS" COMPOSE_PROJECT_NAME --default ai-model-serving-platform
    )"
  fi
  project_name="${project_name:-ai-model-serving-platform}"

  COMPOSE_CHECKOUT_ROOT="$(cd "$root" && pwd -P)"
  COMPOSE_PROJECT_NAME="$project_name"
  COMPOSE_PROJECT_NAME_EFFECTIVE="$project_name"
  COMPOSE_SERVICE_ENV_FILE="$ENV_FILE_ABS"
  COMPOSE_CONTEXT_FILE_ARGS=(
    --project-name "$COMPOSE_PROJECT_NAME_EFFECTIVE"
    -f "$COMPOSE_FILE_ABS"
  )

  export \
    COMPOSE_CHECKOUT_ROOT ENV_FILE COMPOSE_FILE ENV_FILE_ABS COMPOSE_FILE_ABS \
    COMPOSE_PROJECT_NAME COMPOSE_PROJECT_NAME_EFFECTIVE COMPOSE_SERVICE_ENV_FILE
}

# 동일 Docker daemon에서 다른 working directory가 같은 Compose project name을
# 사용 중이면 up/down/restart는 그 컨테이너를 재생성·중지할 수 있으므로 항상 거부한다.
compose_context_assert_mutation_safe() {
  local python_bin="${PYTHON_BIN:-$(command -v python3 || command -v python)}"
  local ownership_tool
  command -v docker >/dev/null 2>&1 || return 0
  ownership_tool="$(cd "$(dirname "${BASH_SOURCE[0]}")/../ops" && pwd -P)/compose_ownership.py"
  "$python_bin" "$ownership_tool" --root "$COMPOSE_CHECKOUT_ROOT" \
    assert-project --project "$COMPOSE_PROJECT_NAME_EFFECTIVE"
}

compose_context_run() {
  docker compose \
    "${COMPOSE_CONTEXT_FILE_ARGS[@]}" \
    --env-file "$ENV_FILE_ABS" \
    "$@"
}
