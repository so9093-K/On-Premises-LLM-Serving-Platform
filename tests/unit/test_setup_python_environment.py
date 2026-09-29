from __future__ import annotations

import runpy
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.build import setup_python_environment
from scripts.build.setup_python_environment import build_sync_command


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_profile_excludes_quality_dependencies() -> None:
    command = build_sync_command("uv", Path("/python"), "runtime")

    assert command == [
        "uv",
        "sync",
        "--locked",
        "--no-group",
        "quality",
        "--python",
        "/python",
    ]


def test_make_up_preflight_dependencies_survive_runtime_sync() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = set(document["project"]["dependencies"])
    quality_dependencies = set(document["dependency-groups"]["quality"])

    assert "Jinja2==3.1.6" in runtime_dependencies
    assert "Jinja2==3.1.6" not in quality_dependencies


def test_development_profile_includes_quality_dependencies() -> None:
    command = build_sync_command("uv", Path("/python"), "development")

    assert command == [
        "uv",
        "sync",
        "--locked",
        "--group",
        "quality",
        "--python",
        "/python",
    ]


def test_setup_dev_wrapper_selects_development_profile(monkeypatch) -> None:
    captured: list[list[str]] = []

    def fake_main(argv: list[str] | None = None) -> int:
        captured.append(list(argv or []))
        return 0

    monkeypatch.setattr(setup_python_environment, "main", fake_main)

    try:
        runpy.run_path(str(ROOT / "scripts/build/setup_dev.py"), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0

    assert captured == [["--profile", "development"]]


def test_quiet_runtime_bootstrap_hides_success_output(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(setup_python_environment, "ROOT", tmp_path)

    setup_python_environment._run_bootstrap_step(
        [sys.executable, "-c", "print('internal bootstrap noise')"],
        label="bootstrap test",
        quiet=True,
    )

    assert capsys.readouterr().out == ""
    assert not list((tmp_path / ".runtime" / "operator-logs").glob("*.log"))


def test_runtime_bootstrap_failure_uses_platform_vocabulary(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(setup_python_environment, "ROOT", tmp_path)

    with pytest.raises(subprocess.CalledProcessError):
        setup_python_environment._run_bootstrap_step(
            [sys.executable, "-c", "raise SystemExit(7)"],
            label="bootstrap failure",
            quiet=True,
        )

    error = capsys.readouterr().err
    assert "[platform] bootstrap failure failed" in error
    assert "[setup]" not in error


def test_uv_version_specifier_matches_the_pyproject_contract() -> None:
    specifier = setup_python_environment.required_uv_version(ROOT)

    assert specifier == ">=0.12.11,<0.13"
    assert setup_python_environment.version_satisfies("0.12.11", specifier) is True
    assert setup_python_environment.version_satisfies("0.12.20", specifier) is True
    assert setup_python_environment.version_satisfies("0.11.9", specifier) is False
    assert setup_python_environment.version_satisfies("0.13.0", specifier) is False
    # 단순 비교로 판단할 수 없는 specifier는 uv 자신의 검사에 맡긴다.
    assert setup_python_environment.version_satisfies("0.12.1", "~=0.12") is None


def test_outdated_uv_fails_before_sync_with_an_install_hint(tmp_path: Path) -> None:
    fake_uv = tmp_path / "uv"
    fake_uv.write_text("#!/bin/sh\necho 'uv 0.11.3 (abc 2026-01-01)'\n", encoding="utf-8")
    fake_uv.chmod(0o755)

    with pytest.raises(RuntimeError) as excinfo:
        setup_python_environment.check_uv_version(str(fake_uv), ROOT)

    message = str(excinfo.value)
    assert "uv 0.11.3 does not match tool.uv.required-version '>=0.12.11,<0.13'" in message
    assert "https://docs.astral.sh/uv/getting-started/installation/" in message
    assert "uv self update 0.12.11" in message


def test_matching_uv_passes_the_precheck(tmp_path: Path) -> None:
    fake_uv = tmp_path / "uv"
    fake_uv.write_text("#!/bin/sh\necho 'uv 0.12.20'\n", encoding="utf-8")
    fake_uv.chmod(0o755)

    setup_python_environment.check_uv_version(str(fake_uv), ROOT)
