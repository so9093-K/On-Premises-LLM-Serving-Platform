#!/usr/bin/env bash
# Platform image가 어느 소스에서 만들어졌는지 OCI label에 기록하기 위한 공통 조회.
#
# 사용: source scripts/lib/source_provenance.sh; read_source_provenance
#       -> SOURCE_REVISION, SOURCE_STATE 를 설정한다.

read_source_provenance() {
  SOURCE_REVISION="unknown"
  SOURCE_STATE="unknown"
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    SOURCE_REVISION="$(git rev-parse HEAD)"
    if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
      SOURCE_STATE="dirty"
    else
      SOURCE_STATE="clean"
    fi
  fi
}
