"""검증 실행의 성공·실패·결과 누락 계약을 보호한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.validation import run_suite


def latest_summary(root: Path, suite: str) -> tuple[dict, dict, Path]:
    outputs = list((root / suite).iterdir())
    assert len(outputs) == 1
    output = outputs[0]
    return (
        json.loads((output / "manifest.json").read_text(encoding="utf-8")),
        json.loads((output / "summary.json").read_text(encoding="utf-8")),
        output,
    )


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ('<testsuites><testcase name="node"/></testsuites>', {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}),
        (
            '<testsuites><testsuite><testcase name="ok"/><testcase name="bad"><failure/></testcase>'
            '<testcase name="skip"><skipped/></testcase></testsuite></testsuites>',
            {"tests": 3, "failures": 1, "errors": 0, "skipped": 1},
        ),
    ],
)
def test_junit_counts_supports_node_and_pytest(tmp_path, xml, expected):
    path = tmp_path / "junit.xml"
    path.write_text(xml, encoding="utf-8")
    assert run_suite.junit_counts(path) == expected


@pytest.mark.parametrize(
    ("xml", "exit_code", "expected_status", "expected_exit"),
    [
        ('<testsuite><testcase name="ok"/></testsuite>', 0, "passed", 0),
        ('<testsuite><testcase name="bad"><failure/></testcase></testsuite>', 1, "test_failed", 1),
        ('<testsuite><testcase name="bad"><error/></testcase></testsuite>', 2, "execution_error", 2),
        ("<testsuite/>", 0, "execution_error", 2),
        ("<not-junit/>", 0, "execution_error", 2),
    ],
)
def test_native_runner_outcome_is_not_reinterpreted(monkeypatch, tmp_path, xml, exit_code, expected_status, expected_exit):
    def invocation(_suite, junit):
        code = (
            "from pathlib import Path; import sys; "
            f"Path({str(junit)!r}).write_text({xml!r}, encoding='utf-8'); "
            f"sys.exit({exit_code})"
        )
        return [sys.executable, "-c", code], tmp_path, {}

    monkeypatch.setattr(run_suite, "invocation", invocation)
    monkeypatch.setattr(run_suite, "source_revision", lambda: None)
    assert run_suite.run("pytest", tmp_path) == expected_exit
    manifest, summary, output = latest_summary(tmp_path, "pytest")
    assert summary["status"] == expected_status
    assert summary["exit_code"] == exit_code
    assert summary["junit"] == ("junit.xml" if summary["counts"] else None)
    assert manifest["source_revision"] is None
    assert manifest["run_id"] == summary["run_id"] == output.name


def test_missing_junit_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(run_suite, "invocation", lambda suite, junit: ([sys.executable, "-c", "pass"], tmp_path, {}))
    monkeypatch.setattr(run_suite, "source_revision", lambda: None)
    assert run_suite.run("node", tmp_path) == 2
    _, summary, _ = latest_summary(tmp_path, "node")
    assert summary["status"] == "execution_error"
    assert summary["junit"] is None


@pytest.mark.parametrize(("exit_code", "expected"), [(0, "passed"), (3, "test_failed")])
def test_browser_script_report_is_one_smoke_case(monkeypatch, tmp_path, exit_code, expected):
    monkeypatch.setattr(
        run_suite, "invocation",
        lambda suite, junit: ([sys.executable, "-c", f"import sys;sys.exit({exit_code})"], tmp_path, {}),
    )
    monkeypatch.setattr(run_suite, "source_revision", lambda: None)
    assert run_suite.run("playwright", tmp_path) == exit_code
    _, summary, output = latest_summary(tmp_path, "playwright")
    assert summary["status"] == expected
    assert summary["counts"]["tests"] == 1
    assert summary["counts"]["failures"] == int(exit_code != 0)
    assert run_suite.junit_counts(output / "junit.xml") == summary["counts"]


def test_validator_does_not_invent_junit_tests(monkeypatch, tmp_path):
    monkeypatch.setattr(run_suite, "invocation", lambda suite, junit: ([sys.executable, "-c", "raise SystemExit(4)"], tmp_path, {}))
    monkeypatch.setattr(run_suite, "source_revision", lambda: None)
    assert run_suite.run("validate", tmp_path) == 4
    _, summary, output = latest_summary(tmp_path, "validate")
    assert summary["status"] == "validation_failed"
    assert summary["counts"] is None
    assert not (output / "junit.xml").exists()


def test_runner_launch_failure_is_not_test_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(run_suite, "invocation", lambda suite, junit: (["a-command-that-does-not-exist-1234"], tmp_path, {}))
    monkeypatch.setattr(run_suite, "source_revision", lambda: None)
    assert run_suite.run("pytest", tmp_path) == 127
    _, summary, _ = latest_summary(tmp_path, "pytest")
    assert summary["status"] == "execution_error"
    assert summary["diagnostic"] == "FileNotFoundError"
