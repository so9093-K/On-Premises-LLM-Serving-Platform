#!/usr/bin/env bash
# Platform image가 어느 소스에서 만들어졌는지 OCI label에 기록하기 위한 공통 조회.
#
# 사용: source scripts/lib/source_provenance.sh; read_source_provenance
#       -> SOURCE_REVISION, SOURCE_STATE, SOURCE_DIGEST, SOURCE_RUNTIME_DIGEST를 설정한다.

read_source_provenance() {
  local source_root provenance_python provenance
  source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  provenance_python="${PYTHON_BIN:-$(command -v python3.12 || command -v python3.13 || command -v python3 || command -v python)}"
  if ! provenance="$("$provenance_python" "$source_root/scripts/lib/source_provenance.py" --artifact "${1:-platform}")"; then
    return 2
  fi
  IFS=$'\t' read -r SOURCE_REVISION SOURCE_STATE SOURCE_DIGEST SOURCE_RUNTIME_DIGEST <<< "$provenance"
  if [[ "$SOURCE_STATE" == "local" ]]; then
    SOURCE_REVISION=""
  fi
}
