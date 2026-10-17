#!/usr/bin/env python3
"""기존 검증 러너의 판정 권한을 보존하면서 공통 실행 결과를 기록한다."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "ui" / "control-plane"
SUITES = ("validate", "pytest", "node", "playwright")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    revision = result.stdout.strip()
    return revision if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision) else None


def junit_counts(path: Path) -> dict[str, int]:
    """pytest의 nested suites와 Node의 direct testcases를 동일하게 읽는다."""
    root = ET.parse(path).getroot()
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected JUnit root element")
    cases = list(root.iter("testcase"))
    return {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }


def browser_junit(path: Path, exit_code: int, duration: float) -> None:
    """기존 Python Playwright 스크립트 전체를 하나의 smoke 검사로 보고한다."""
    suite = ET.Element("testsuite", {
        "name": "operator-browser-smoke",
        "tests": "1",
        "failures": str(int(exit_code != 0)),
        "errors": "0",
    })
    case = ET.SubElement(suite, "testcase", {
        "classname": "playwright.smoke",
        "name": "operator_workflows",
        "time": f"{duration:.3f}",
    })
    if exit_code:
        ET.SubElement(case, "failure", {
            "message": f"browser smoke exited with code {exit_code}",
            "type": "SmokeFailure",
        })
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def invocation(suite: str, junit: Path) -> tuple[list[str], Path, dict[str, str]]:
    env = os.environ.copy()
    python = sys.executable
    if suite == "validate":
        return ["bash", "scripts/validation/run_validate.sh"], ROOT, env
    if suite == "pytest":
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return [
            python, "-m", "pytest", "-q", "-p", "xdist",
            "-n", env.get("PYTEST_WORKERS", "auto"),
            f"--junitxml={junit}",
        ], ROOT, env
    if suite == "node":
        tests = sorted(str(path.relative_to(CONSOLE)) for path in (CONSOLE / "tests").glob("*.test.mjs"))
        return [
            "node", "--experimental-strip-types", "--test",
            "--test-reporter=spec", "--test-reporter-destination=stdout",
            "--test-reporter=junit", f"--test-reporter-destination={junit}",
            *tests,
        ], CONSOLE, env
    if suite == "playwright":
        return [python, "scripts/validation/console_browser_smoke.py"], ROOT, env
    raise ValueError(f"unknown suite: {suite}")


def run(suite: str, output_root: Path) -> int:
    run_id = uuid.uuid4().hex
    output = output_root.resolve() / suite / run_id
    output.mkdir(parents=True, exist_ok=False)
    junit = output / "junit.xml"
    command, cwd, env = invocation(suite, junit)
    started_at = utc_now()
    started = time.monotonic()
    exit_code = 127
    launch_error = None
    try:
        exit_code = subprocess.run(command, cwd=cwd, env=env, check=False).returncode
    except OSError as exc:
        # 실행 파일 부재 등의 실행 오류는 테스트 실패로 둔갑시키지 않는다.
        launch_error = type(exc).__name__
        print(f"[validation] {suite}: runner could not start ({launch_error})", file=sys.stderr)
    duration = round(time.monotonic() - started, 3)

    if suite == "playwright" and launch_error is None:
        browser_junit(junit, exit_code, duration)

    counts = None
    report_error = None
    if suite != "validate":
        try:
            counts = junit_counts(junit)
            if counts["tests"] == 0:
                raise ValueError("JUnit has no testcases")
        except (OSError, ET.ParseError, ValueError) as exc:
            report_error = type(exc).__name__
            counts = None

    if launch_error or report_error:
        status = "execution_error"
    elif suite == "validate":
        status = "passed" if exit_code == 0 else "validation_failed"
    elif exit_code != 0 or counts["failures"] or counts["errors"]:
        status = "test_failed" if counts["failures"] else "execution_error"
    else:
        status = "passed"

    # 성공하지 않은 결과가 성공으로 승격되지 않도록 원래 exit code를 유지한다.
    final_code = exit_code if exit_code != 0 else (0 if status == "passed" else 2)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "suite": suite,
        "runner": {"validate": "shell", "pytest": "pytest", "node": "node:test", "playwright": "python-playwright"}[suite],
        "source_revision": source_revision(),
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": duration,
        "scope": "browser_mock" if suite == "playwright" else "deterministic",
    }
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "counts": counts,
        "junit": "junit.xml" if counts is not None else None,
        "diagnostic": launch_error or report_error,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[validation] {suite}: {status} (exit={final_code}, report={output})", flush=True)
    return final_code


def main() -> int:
    parser = argparse.ArgumentParser(description="CI 중립적인 테스트 실행·결과 수집")
    parser.add_argument("suite", choices=SUITES)
    parser.add_argument(
        "--output-root", type=Path,
        default=Path(os.environ.get("VALIDATION_REPORT_DIR", ROOT / "reports" / "validation")),
    )
    args = parser.parse_args()
    return run(args.suite, args.output_root)


if __name__ == "__main__":
    sys.exit(main())
