#!/usr/bin/env bash

# compose-up이 fingerprint 기반으로 반영할 bind-mounted 설정 목록을 compose 파일에서 파생한다.
# "compose-service:source path ..." 형식으로 한 줄씩 출력한다.
#
# 예전에는 이 목록을 손으로 적어뒀다. compose와 갈라져도 확인하는 코드가 없어서
# promtail이 compose에서 사라진 뒤에도 배포 상태 파일이 남아 있었고, 적어둔 경로가
# 실제 마운트보다 거칠어서(예: 파일 두 개만 마운트하는데 `ops/prometheus` 전체)
# 지문 범위도 실제와 달랐다.
#
# 파생 규칙:
#   - project root 상대 경로(`..`로 시작)를 bind-mount하는 서비스만 본다.
#   - `.runtime/*`는 runtime state이므로 config fingerprint 대상에서 뺀다.
#   - project root 밖으로 나가는 경로도 뺀다.
#   - GPU를 예약한 서비스는 뺀다. 설정 변경으로 모델을 콜드 스타트시키지 않는다는
#     정책이며, 모델 런타임 입력은 의도적인 교체 경로가 담당한다. 이 판단만이
#     compose에서 파생되지 않는 정책인데, GPU 예약 자체는 compose가 이미 선언하고
#     있으므로 여기에 서비스 이름을 적을 필요는 없다.
bind_mounted_config_service_specs() {
  local source_root="${1:?source root required}"
  local compose_file="${2:?compose file required}"
  "${PYTHON_BIN:-$(command -v python3.12 || command -v python3 || command -v python)}" - \
    "${source_root}" "${compose_file}" <<'PY'
import os
import sys

import yaml

source_root, compose_file = sys.argv[1], sys.argv[2]
root = os.path.realpath(source_root)
compose_path = os.path.join(root, compose_file)
compose_dir = os.path.dirname(compose_path)
with open(compose_path, encoding="utf-8") as handle:
    document = yaml.safe_load(handle)

for service, definition in sorted((document.get("services") or {}).items()):
    reservations = (
        ((definition.get("deploy") or {}).get("resources") or {}).get("reservations") or {}
    )
    if reservations.get("devices"):
        continue
    paths = []
    for volume in definition.get("volumes") or []:
        if not isinstance(volume, str) or not volume.startswith(".."):
            continue
        joined = os.path.normpath(os.path.join(compose_dir, volume.split(":", 1)[0]))
        if ".runtime" in os.path.relpath(joined, root).split(os.sep):
            continue
        source = os.path.realpath(joined)
        if source == root or os.path.commonpath([source, root]) != root:
            continue
        paths.append(os.path.relpath(source, root))
    if paths:
        print("{}:{}".format(service, " ".join(sorted(set(paths)))))
PY
}

# 주어진 source root 아래의 설정 내용으로 안정적인 fingerprint를 만든다.
# 파일명도 sha256sum 입력에 포함되므로, 내용 변경뿐 아니라 추가/삭제도 감지한다.
bind_mounted_config_fingerprint() (
  local source_root="$1"
  shift
  cd "${source_root}"
  {
    local relative_path
    for relative_path in "$@"; do
      find -- "${relative_path}" -type f -print0
    done
  } | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}'
)

