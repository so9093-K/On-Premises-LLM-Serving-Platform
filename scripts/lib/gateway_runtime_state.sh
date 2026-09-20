#!/usr/bin/env bash
# compose-up이 Gateway의 desired state(runtime-state.json)를 초기화하는 방법을
# 한 곳에 모은다.
#
# 이 파일의 writer는 Gateway 하나다. compose-up은 어떤 런타임을 정지 상태로 둘지
# env directive로 전달만 하고, 기록은 Gateway가 기동 시 한 번 수행한다.

# 상태 파일이 놓이는 호스트 경로. compose 파일의 gateway bind mount 원본과 같아야
# 한다(ops/compose/full-stack.private-network.yaml의 `../../.runtime/gateway`).
GATEWAY_RUNTIME_DIR_RELPATH=".runtime/gateway"
REQUEST_EVENT_LOG_DIR_RELPATH=".runtime/request-events"

# 이 함수로 준비하는 디렉터리는 platform image의 non-root 프로세스가 쓰는 곳이다.
# Gateway state는 Gateway만, request event 디렉터리는 Gateway/Risk Adapter가 각자
# 서비스별 파일을 쓴다.
# bind mount라 소유권은 호스트가 정하는데, 이미지 안의 uid와 호스트 uid 사이에는
# 아무 관계가 없다. 그래서 "누가 먼저 만들었나"가 소유권을 결정해 버린다:
#
#   - compose가 먼저 닿으면 Docker가 root 소유로 만든다 -> 컨테이너가 못 쓴다.
#   - host 사용자가 먼저 만들면 그 사용자 소유가 된다 -> 역시 컨테이너가 못 쓴다.
#
# 존재 여부만 확인하면 이미 잘못된 소유권으로 굳은 디렉터리를 그대로 통과시킨다.
# 그래서 매번 소유권까지 단언한다. uid는 하드코딩하지 않고 이미지에게 직접 묻는다
# -- 박아두면 이미지가 실행 사용자를 바꾸는 순간 다시 어긋난다.
ensure_platform_runtime_dir() {
  local dir="$1"
  local image="$2"
  local parent name owner
  parent="$(dirname "${dir}")"
  name="$(basename "${dir}")"
  mkdir -p "${parent}" || return 1
  # docker의 bind mount는 절대 경로만 받는다. 상대 경로를 넘기면 named volume으로
  # 해석되어 엉뚱한 곳을 만든다.
  parent="$(cd "${parent}" && pwd)" || return 1

  if ! owner="$(docker run --rm --entrypoint sh "${image}" -c 'printf "%s:%s" "$(id -u)" "$(id -g)"')"; then
    echo "[runtime-state] ERROR: failed to read the runtime uid/gid from ${image}" >&2
    return 1
  fi

  # 호스트 사용자에게는 chown 권한이 없을 수 있으므로 컨테이너의 root로 단언한다.
  if ! docker run --rm -u 0:0 -v "${parent}:/mnt" --entrypoint sh "${image}" \
    -c "mkdir -p /mnt/${name} && chown -R ${owner} /mnt/${name}"; then
    echo "[runtime-state] ERROR: failed to prepare ${dir} for ${owner}" >&2
    return 1
  fi
  echo "[runtime-state] ${dir} owned by ${owner}"
}

# 기존 호출부와 이력에서 쓰는 이름은 Gateway state 경로용 별칭으로 유지한다.
ensure_gateway_runtime_dir() {
  ensure_platform_runtime_dir "$@"
}

# Gateway는 콤마로 구분된 runtime key 목록과 startup generation을 읽는다.
# generation은 compose-up 한 번의 startup policy 적용을 식별하는 내부 토큰이며
# operator가 persistent .env에서 관리하는 release/version 값이 아니다.
export_runtime_startup_directive() {
  local startup_generation="$1"
  shift
  local joined=""
  if (($#)); then
    printf -v joined '%s,' "$@"
    joined="${joined%,}"
  fi
  export RUNTIME_STARTUP_DEFERRED_KEYS="${joined}"
  if [[ -n "${startup_generation}" ]]; then
    export RUNTIME_STARTUP_GENERATION="${startup_generation}"
  fi
  if [[ -n "${joined}" ]]; then
    echo "[runtime-state] startup deferred runtimes: ${joined}"
  fi
}

