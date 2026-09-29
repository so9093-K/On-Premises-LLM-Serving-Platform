"""Operator-facing progress for long lifecycle steps.

A step's raw output goes to a log file so it never becomes the operator UI. That
alone makes a 30-minute image build or model download indistinguishable from a
hang, so while the step runs the terminal shows one live line with the elapsed
time and the step's latest output line. Redirected output (CI, `tee`) gets a
periodic heartbeat instead of carriage-return redraws.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TextIO

POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 30.0
LOG_HINT_AFTER_SECONDS = 15.0
# 마지막 줄만 필요하다. 로그 전체를 매번 읽지 않는다.
_TAIL_BYTES = 8192
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CLEAR_LINE = "\r\x1b[2K"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def last_output_line(path: Path) -> str:
    """Return the latest non-empty line, without colors or progress-bar redraws."""
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - _TAIL_BYTES))
            data = stream.read()
    except OSError:
        return ""
    # docker/pip progress bar는 \r로 같은 줄을 다시 그린다. \r도 줄 경계로 본다.
    for line in reversed(re.split(r"[\r\n]", data.decode("utf-8", errors="replace"))):
        cleaned = "".join(char for char in _ANSI.sub("", line) if char.isprintable()).strip()
        if cleaned:
            return cleaned
    return ""


def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def fit(text: str, width: int) -> str:
    """Truncate to terminal cells so a wide (e.g. Korean) line never wraps the status."""
    if sum(_char_width(char) for char in text) <= width:
        return text
    kept: list[str] = []
    used = 0
    for char in text:
        char_width = _char_width(char)
        if used + char_width > width - 1:
            break
        kept.append(char)
        used += char_width
    return "".join(kept) + "…"


def run_with_progress(
    label: str,
    command: Sequence[str],
    *,
    log_path: Path,
    log_display: str,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    interactive: bool | None = None,
    prefix: str = "[platform]",
    clock: Callable[[], float] = time.monotonic,
) -> tuple[int, float]:
    """Run ``command`` with output captured in ``log_path``; return (exit code, seconds)."""
    out = stream if stream is not None else sys.stdout
    live = out.isatty() if interactive is None else interactive
    started = clock()
    next_heartbeat = started + HEARTBEAT_SECONDS
    hinted = False
    status_visible = False

    def clear_status() -> None:
        nonlocal status_visible
        if status_visible:
            out.write(_CLEAR_LINE)
            out.flush()
            status_visible = False

    print(f"{prefix} {label}...", file=out, flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            while True:
                try:
                    returncode = process.wait(timeout=POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = clock()
                elapsed = now - started
                if not hinted and elapsed >= LOG_HINT_AFTER_SECONDS:
                    clear_status()
                    print(f"{prefix}   live output: tail -f {log_display}", file=out, flush=True)
                    hinted = True
                latest = last_output_line(log_path)
                if live:
                    columns = shutil.get_terminal_size((100, 24)).columns
                    line = f"{prefix}   {format_elapsed(elapsed)}" + (f" · {latest}" if latest else "")
                    out.write(_CLEAR_LINE + fit(line, max(20, columns - 1)))
                    out.flush()
                    status_visible = True
                elif now >= next_heartbeat:
                    detail = f" · {fit(latest, 120)}" if latest else ""
                    print(f"{prefix}   {label}: {format_elapsed(elapsed)} elapsed{detail}", file=out, flush=True)
                    next_heartbeat = now + HEARTBEAT_SECONDS
        except BaseException as exc:
            clear_status()
            # Ctrl-C는 같은 process group의 child에도 전달된다. 정리할 시간을 준 뒤에만 끝낸다.
            grace = 5 if isinstance(exc, KeyboardInterrupt) else 0
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    clear_status()
    return returncode, clock() - started
