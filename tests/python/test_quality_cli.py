"""품질 실행기의 프로세스 종료 상태 전달 계약."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from scripts.quality_cli import _invoke


def test_signal_exit_is_reported_as_shell_status(tmp_path: Path) -> None:
    # 자식 프로세스만 종료한다. pytest 및 플랫폼 서비스 프로세스는 종료하지 않는다.
    code = _invoke(
        "signal",
        [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
        cwd=tmp_path,
    )
    assert code == 128 + signal.SIGTERM


def test_missing_command_is_reported_as_127(tmp_path: Path) -> None:
    assert _invoke("missing", ["__missing_quality_runner_7472__"], cwd=tmp_path) == 127
