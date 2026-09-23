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


def test_make_up_uses_runtime_profile_and_setup_dev_keeps_dev_entrypoint() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    up_block = makefile.split("up: ##", 1)[1].split("\n\n", 1)[0]
    assert (
        '"$(PYTHON)" scripts/build/setup_python_environment.py --profile runtime'
        in up_block
    )
    assert '"$(PYTHON)" scripts/build/setup_dev.py' in makefile


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
