"""변경된 파일에 필요한 CI 검증만 선택한다. 알 수 없는 변경은 전체 검증한다."""
from __future__ import annotations

import argparse
import json
import sys

CHECKS = ("app_tests", "macos", "console", "browser", "platform_image", "loki")


def select_checks(paths: list[str], *, full: bool = False) -> dict[str, bool]:
    """위험이 불분명하면 검증을 생략하지 않는다."""
    required = dict.fromkeys(CHECKS, False)
    if full or not paths:
        return dict.fromkeys(CHECKS, True)
    for path in paths:
        if path in {"README.md", "CHANGELOG.md", "CONTRIBUTING.md"} or path.startswith("docs/"):
            continue
        if path.startswith("tests/"):
            required["app_tests"] = True
            required["macos"] = True
            continue
        if path.startswith("src/ai_model_serving/static/control-plane/"):
            required["console"] = True
            required["browser"] = True
            required["platform_image"] = True
            continue
        if path.startswith("src/ai_model_serving/"):
            required["app_tests"] = True
            required["macos"] = True
            required["platform_image"] = True
            continue
        if path.startswith("ui/control-plane/tests/"):
            required["console"] = True
            continue
        if path.startswith("ui/control-plane/src/"):
            required["console"] = True
            required["browser"] = True
            required["platform_image"] = True
            continue
        if path == "scripts/validation/console_browser_smoke.py":
            required["browser"] = True
            continue
        if path == "scripts/validation/grafana_loki_smoke.py" or path.startswith("ops/loki/"):
            required["loki"] = True
            continue
        return dict.fromkeys(CHECKS, True)
    return required


def output_lines(checks: dict[str, bool]) -> list[str]:
    matrix = {"include": [{"os": "ubuntu-24.04", "python_version": "3.12"}]}
    if checks["macos"]:
        matrix["include"].append({"os": "macos-15", "python_version": "3.13"})
    return [
        *(f"{name}={'true' if checks[name] else 'false'}" for name in CHECKS),
        "matrix=" + json.dumps(matrix, separators=(",", ":")),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="변경 영향 기반 CI 검증 분류")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    raw = b"" if args.full else sys.stdin.buffer.read()
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    lines = output_lines(select_checks(paths, full=args.full))
    print("\n".join(lines))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as result:
            result.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
