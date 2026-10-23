#!/usr/bin/env python3
"""품질 명령의 공통 실행 진입점. 개별 테스트 판정은 Native Runner가 소유한다."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "ui" / "control-plane"
TEST_BOOTSTRAP_HINT = "프런트엔드 Runner가 없습니다. make setup-test-runners를 실행하세요."


def _invoke(name: str, command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    if shutil.which(command[0]) is None:
        print(f"[quality] {name}: 실행 파일이 없습니다: {command[0]}", file=sys.stderr)
        return 127
    print(f"[quality] {name}: {' '.join(command)}", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, env=env, check=False)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"[quality] {name}: 실행 실패: {exc}", file=sys.stderr)
        return 127
    if result.returncode != 0:
        print(f"[quality] {name}: 실패 (exit {result.returncode})", file=sys.stderr)
    return result.returncode


def _native_runner(name: str, junit_dir: Path | None) -> int:
    env = os.environ.copy()
    if name == "python":
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        command = [sys.executable, "-m", "pytest", "-q", "tests/python"]
        if junit_dir is not None:
            command.append(f"--junitxml={junit_dir / 'pytest.xml'}")
        return _invoke("pytest", command, cwd=ROOT, env=env)

    binary = CONSOLE / "node_modules" / ".bin" / ("vitest" if name == "frontend" else "playwright")
    if not binary.is_file():
        print(f"[quality] {name}: {TEST_BOOTSTRAP_HINT}", file=sys.stderr)
        return 127

    if name == "frontend":
        command = ["npm", "run", "test:unit"]
        if junit_dir is not None:
            command += ["--", "--reporter=default", "--reporter=junit", f"--outputFile.junit={junit_dir / 'vitest.xml'}"]
    else:
        command = ["npm", "run", "test:browser"]
        if junit_dir is not None:
            env["PLAYWRIGHT_JUNIT_OUTPUT_FILE"] = str(junit_dir / "playwright.xml")
            command += ["--", "--reporter=line,junit"]
    return _invoke(name, command, cwd=CONSOLE, env=env)


def _run_suites(names: tuple[str, ...], junit_dir: Path | None) -> int:
    if junit_dir is not None:
        junit_dir = junit_dir.resolve()
        junit_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, int]] = []
    for name in names:
        code = _native_runner(name, junit_dir)
        if code != 0:
            failures.append((name, code))
    if failures:
        print("[quality] 실패: " + ", ".join(f"{name}={code}" for name, code in failures), file=sys.stderr)
        return failures[0][1]
    print("[quality] 완료: " + ", ".join(names))
    return 0


def _validate() -> int:
    commands = (
        ("Python 정적 검사", [sys.executable, "-m", "ruff", "check", "--quiet", "src", "scripts", "--extend-exclude", "scripts/validation"], ROOT),
        ("생성 산출물 Drift", [sys.executable, "scripts/render_runtime_assets.py", "--check"], ROOT),
    )
    failures = []
    for label, command, cwd in commands:
        status = _invoke(label, command, cwd=cwd)
        if status != 0:
            failures.append(status)
    return failures[0] if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="프로젝트 품질 실행 CLI (Native Runner)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Native Runner Suite 실행")
    run.add_argument("suite", choices=("python", "frontend", "browser", "all"))
    run.add_argument("--junit-dir", type=Path, help="선택적 JUnit XML 출력 디렉터리")
    sub.add_parser("validate", help="최소 정적 검사 및 생성 산출물 확인")
    sub.add_parser("check", help="정적 검사, Python·프런트엔드, Control Plane 빌드")
    args = parser.parse_args(argv)
    if args.command == "run":
        suites = ("python", "frontend", "browser") if args.suite == "all" else (args.suite,)
        return _run_suites(suites, args.junit_dir)
    if args.command == "validate":
        return _validate()

    failed = []
    for name, run_step in (
        ("validate", _validate),
        ("python", lambda: _run_suites(("python",), None)),
        ("frontend", lambda: _run_suites(("frontend",), None)),
        ("console", lambda: _invoke("Control Plane 소스·빌드", ["npm", "run", "check:source"], cwd=CONSOLE)),
    ):
        status = run_step()
        if status:
            failed.append((name, status))
    if failed:
        print("[quality] check 실패: " + ", ".join(name for name, _ in failed), file=sys.stderr)
        return failed[0][1]
    print("[quality] check 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
