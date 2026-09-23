#!/usr/bin/env python3
"""Synchronize the Platform Python environment from the project lock."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALITY_GROUP = "quality"
PROFILES = ("runtime", "development")


def _interpreter_minor(executable: Path) -> str:
    return subprocess.check_output(
        [str(executable), "-c", 'import sys; print("%s.%s" % sys.version_info[:2])'],
        text=True,
    ).strip()


def _uv_binary() -> str:
    configured = os.environ.get("UV_BIN")
    executable = configured or shutil.which("uv")
    if not executable:
        raise RuntimeError(
            "uv is required to prepare Python environments; install the version "
            "declared by pyproject.toml or set UV_BIN=/path/to/uv"
        )
    return executable


def _check_existing_environment(root: Path, selected: Path) -> None:
    directory = root / ".venv"
    if not directory.exists():
        return
    python = directory / "bin/python"
    if not (directory / "pyvenv.cfg").is_file() or not python.is_file():
        raise RuntimeError(
            "Existing .venv is not a usable virtual environment; inspect it before retrying."
        )
    current_minor = _interpreter_minor(python)
    selected_minor = _interpreter_minor(selected)
    if current_minor != selected_minor:
        raise RuntimeError(
            f"Existing .venv uses Python {current_minor}, selected interpreter uses "
            f"{selected_minor}. Reuse it with PYTHON_BIN=.venv/bin/python, or move it "
            "aside before creating a new environment."
        )


def build_sync_command(uv_binary: str, selected: Path, profile: str) -> list[str]:
    if profile not in PROFILES:
        raise ValueError(f"unsupported environment profile: {profile}")
    group_args = (
        ["--group", QUALITY_GROUP]
        if profile == "development"
        else ["--no-group", QUALITY_GROUP]
    )
    return [
        uv_binary,
        "sync",
        "--locked",
        *group_args,
        "--python",
        str(selected),
    ]


def _run_bootstrap_step(
    command: list[str],
    *,
    label: str,
    cwd: Path | None = None,
    quiet: bool,
) -> None:
    if not quiet:
        subprocess.run(command, cwd=cwd, check=True)
        return

    safe = "".join(char if char.isalnum() else "-" for char in label.lower()).strip("-")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = ROOT / ".runtime" / "operator-logs" / f"{stamp}-{safe}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode == 0:
        log_path.unlink(missing_ok=True)
        return

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    excerpt = "\n".join(lines[-20:])
    if excerpt:
        print(excerpt, file=sys.stderr)
    print(
        f"[setup] {label} failed; full output: {log_path.relative_to(ROOT)}",
        file=sys.stderr,
    )
    raise subprocess.CalledProcessError(result.returncode, command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Platform uv.lock에서 목적별 Python 환경을 동기화합니다."
    )
    parser.add_argument("--profile", choices=PROFILES, required=True)
    args = parser.parse_args(argv)
    context = "setup-dev" if args.profile == "development" else "make up"
    quiet = args.profile == "runtime" and os.environ.get("PLATFORM_VERBOSE") != "1"
    try:
        _run_bootstrap_step(
            [
                sys.executable,
                str(ROOT / "scripts/build/check_python.py"),
                "--context",
                context,
            ],
            label="Checking Python runtime",
            quiet=quiet,
        )
        selected = Path(sys.executable).resolve()
        _check_existing_environment(ROOT, selected)
        _run_bootstrap_step(
            build_sync_command(_uv_binary(), selected, args.profile),
            label="Synchronizing Python environment",
            cwd=ROOT,
            quiet=quiet,
        )
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[{context}] {exc}", file=sys.stderr)
        return 2

    if args.profile == "development":
        print("[setup-dev] ready: make check")
    else:
        print("[platform] ✓ Python environment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
