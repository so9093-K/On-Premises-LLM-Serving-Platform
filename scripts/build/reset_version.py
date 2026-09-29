#!/usr/bin/env python3
"""프로젝트 버전을 한 번에 바꾼다.

어떤 파일의 어떤 줄이 버전을 담고 있는지는 scripts/lib/version_refs.py가 유일하게
선언한다. 검증기(scripts/validation/governance/versioning.py)도 같은 표를 읽으므로,
자리를 추가할 때 두 곳을 따로 고칠 일이 없다.

사용법:
  python scripts/build/reset_version.py <version>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.version_refs import (  # noqa: E402
    LINE_REFS,
    is_valid_project_version,
    python_package_version,
)


def apply_line_ref(ref, version: str, py_version: str) -> str:
    """선언된 한 자리를 새 버전으로 갱신하고, 무엇을 바꿨는지 돌려준다."""
    path = ROOT / ref.path
    text = path.read_text(encoding='utf-8')
    expected = ref.expected(version, py_version)
    count = 0 if ref.all_occurrences else 1

    # 치환 문자열을 람다로 준다 -- 버전이나 이미지 이름에 백슬래시/\g 같은 문자가
    # 들어와도 re.sub의 이스케이프로 해석되지 않게 한다.
    updated, replaced = re.subn(ref.pattern, lambda _match: expected, text, count=count)
    if replaced == 0:
        # 표에는 있는데 파일에는 없다. 조용히 넘어가면 그 자리는 영영 옛 버전으로
        # 남는다 -- 실제로 예전 구현이 README.md에 대해 그러고 있었다.
        raise SystemExit(f'{ref.path}: no line matched {ref.pattern!r}')

    path.write_text(updated, encoding='utf-8')
    return f'{ref.path}: {replaced}곳 -> {expected}'


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('usage: reset_version.py <version>')
    version = sys.argv[1].strip()
    if not is_valid_project_version(version):
        raise SystemExit(f'invalid project version: {version}; expected x.y.z or x.y.z-rc.n')

    py_version = python_package_version(version)

    (ROOT / 'VERSION').write_text(version + '\n', encoding='utf-8')
    changes = [apply_line_ref(ref, version, py_version) for ref in LINE_REFS]

    for change in changes:
        print(f'  {change}')
    print(f'version reset to {version}')


if __name__ == '__main__':
    main()
