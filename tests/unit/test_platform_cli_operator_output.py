from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from scripts import platform_cli
from scripts.ops import step_progress
from scripts.ops.step_progress import fit, format_elapsed, last_output_line, run_with_progress


class TickingClock:
    """Each poll advances time so progress output does not depend on wall-clock speed."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def _script(body: str) -> list[str]:
    return [sys.executable, "-c", body]


SLOW_STEP = _script(
    "import sys, time\n"
    "print('\\x1b[32mdownloading\\x1b[0m layer 1', flush=True)\n"
    "time.sleep(0.6)\n"
    "sys.stdout.write('progress 10%\\rprogress 80%\\n'); sys.stdout.flush()\n"
    "time.sleep(0.6)\n"
)


def test_redirected_output_gets_heartbeats_with_the_latest_step_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(step_progress, "POLL_SECONDS", 0.05)
    out = io.StringIO()

    code, elapsed = run_with_progress(
        "Building image",
        SLOW_STEP,
        log_path=tmp_path / "step.log",
        log_display=".runtime/operator-logs/step.log",
        cwd=tmp_path,
        stream=out,
        interactive=False,
        clock=TickingClock(10.0),
    )

    text = out.getvalue()
    assert code == 0
    assert elapsed > 0
    assert text.startswith("[platform] Building image...\n")
    assert "live output: tail -f .runtime/operator-logs/step.log" in text
    assert "Building image: " in text and " elapsed · " in text
    assert "\r" not in text and "\x1b" not in text


def test_terminal_output_redraws_one_status_line_and_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(step_progress, "POLL_SECONDS", 0.05)
    out = io.StringIO()

    code, _ = run_with_progress(
        "Preparing cache",
        SLOW_STEP,
        log_path=tmp_path / "step.log",
        log_display="step.log",
        cwd=tmp_path,
        stream=out,
        interactive=True,
        clock=TickingClock(1.0),
    )

    text = out.getvalue()
    assert code == 0
    assert "\r\x1b[2K[platform]   " in text
    assert "downloading layer 1" in text
    assert text.endswith("\r\x1b[2K"), "status line must be cleared before the ✓ line"


def test_failure_keeps_exit_code_and_log(tmp_path: Path) -> None:
    code, _ = run_with_progress(
        "Failing step",
        _script("import sys; print('boom'); sys.exit(3)"),
        log_path=tmp_path / "step.log",
        log_display="step.log",
        cwd=tmp_path,
        stream=io.StringIO(),
        interactive=False,
    )
    assert code == 3
    assert last_output_line(tmp_path / "step.log") == "boom"


def test_last_line_ignores_colors_and_progress_redraws(tmp_path: Path) -> None:
    log = tmp_path / "step.log"
    log.write_bytes("\x1b[1m#7 [3/8] RUN pip install\x1b[0m\n 12% ▏\r 57% ▌\r\n\n".encode())
    assert last_output_line(log) == "57% ▌"
    assert last_output_line(tmp_path / "missing.log") == ""


def test_status_text_fits_terminal_cells_including_korean() -> None:
    assert fit("abc", 10) == "abc"
    assert fit("abcdefghij", 5) == "abcd…"
    # 한글 한 글자는 두 칸이다.
    assert fit("모델다운로드", 7) == "모델다…"
    assert format_elapsed(9.7) == "9s"
    assert format_elapsed(192) == "3m12s"
    assert format_elapsed(3 * 3600 + 5 * 60) == "3h05m"


def test_run_step_reports_duration_and_removes_successful_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(platform_cli, "ROOT", tmp_path)
    monkeypatch.delenv("PLATFORM_VERBOSE", raising=False)

    platform_cli._run_step("Quick step", sys.executable, "-c", "print('ok')")

    assert "[platform] ✓ Quick step" in capsys.readouterr().out
    assert not list((tmp_path / ".runtime" / "operator-logs").glob("*.log"))

    with pytest.raises(RuntimeError, match=r"Broken step failed after \d+s \(exit 4\)[\s\S]*bad input"):
        platform_cli._run_step("Broken step", sys.executable, "-c", "import sys; print('bad input'); sys.exit(4)")


def test_first_run_lists_targets_with_requirements_and_a_host_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform_cli, "suggested_target", lambda: ("linux-nvidia-dynamic", "NVIDIA driver detected"))

    guidance = platform_cli.first_run_guidance()

    assert "linux-nvidia-dynamic" in guidance and "suggested: NVIDIA driver detected" in guidance
    assert "macos-metal-static" in guidance
    static_line = next(line for line in guidance.splitlines() if "linux-nvidia-static" in line)
    assert "MAIN_URL" in static_line and "unverified" in static_line
    assert guidance.splitlines()[-1] == "example: make up TARGET=linux-nvidia-dynamic ACCESS=local"

    monkeypatch.setattr(platform_cli, "suggested_target", lambda: None)
    assert "example: make up TARGET=<deployment-target>" in platform_cli.first_run_guidance()


def test_suggestion_follows_host_capability_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_cli.sys, "platform", "darwin")
    monkeypatch.setattr(platform_cli.platform, "machine", lambda: "arm64")
    assert platform_cli.suggested_target()[0] == "macos-metal-static"

    monkeypatch.setattr(platform_cli.sys, "platform", "linux")
    monkeypatch.setattr(platform_cli.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    assert platform_cli.suggested_target()[0] == "linux-nvidia-dynamic"

    monkeypatch.setattr(platform_cli.shutil, "which", lambda name: None)
    assert platform_cli.suggested_target() is None


def test_ready_output_points_to_surfaces_the_gateway_reports(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bootstrap = {"links": {"docs": "/docs", "grafana": "http://127.0.0.1:3000/"}}
    monkeypatch.setattr(platform_cli, "_gateway_json", lambda values, path, admin=False: (200, bootstrap))

    platform_cli._print_next_steps({"GATEWAY_PORT": "9400"})
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "[platform]   Console   http://127.0.0.1:9400/admin/console/",
        "[platform]   API docs  http://127.0.0.1:9400/docs",
        "[platform]   Grafana   http://127.0.0.1:3000/",
        "[platform]   Next      make status · make logs · make down",
    ]

    # 문서를 끈 환경이나 Grafana가 없는 target에서는 없는 주소를 안내하지 않는다.
    monkeypatch.setattr(platform_cli, "_gateway_json", lambda values, path, admin=False: (200, {"links": {"docs": None, "grafana": None}}))
    platform_cli._print_next_steps({"GATEWAY_PORT": "9400"})
    assert [line.split()[1] for line in capsys.readouterr().out.splitlines()] == ["Console", "Next"]
