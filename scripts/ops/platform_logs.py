#!/usr/bin/env python3
"""Operator-facing log view.

Default output is structured application events. Raw container/process logs are
available explicitly so diagnostic evidence remains rich without flooding the terminal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUEST_EVENTS = ROOT / ".runtime" / "request-events"
LOCAL_LOGS = ROOT / "logs"
NATIVE_METAL_LOGS = ROOT / ".runtime" / "metal" / "logs"


def _tail_lines(path: Path, limit: int) -> list[str]:
    rows: deque[str] = deque(maxlen=limit)
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                rows.append(line.rstrip("\n"))
    except OSError:
        return []
    return list(rows)


def _structured_events(limit: int, *, all_events: bool = False) -> int:
    files = sorted(
        REQUEST_EVENTS.glob("*.jsonl*"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
    )
    records: deque[dict[str, object]] = deque(maxlen=limit)
    for path in files:
        for line in _tail_lines(path, max(limit * 4, limit)):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            status = payload.get("status_code")
            important = (
                payload.get("error_code") is not None
                or payload.get("diagnostic_code") is not None
                or payload.get("readiness_status") not in (None, "ready")
                or (isinstance(status, int) and status >= 400)
            )
            if all_events or important:
                records.append(payload)
    if not records:
        return 0

    print("Recent application events" if all_events else "Recent error and readiness events")
    for event in records:
        service = str(event.get("service") or "-")
        route = str(event.get("route") or event.get("event") or "-")
        status = event.get("status_code")
        latency = event.get("latency_ms")
        error = event.get("error_code") or event.get("diagnostic_code")
        request_id = event.get("request_id")
        fields = [f"{service:<20}", f"{route:<34}"]
        if status is not None:
            fields.append(f"status={status}")
        if latency is not None:
            fields.append(f"latency={latency}ms")
        if error:
            fields.append(f"error={error}")
        if request_id:
            fields.append(f"request={request_id}")
        print("  " + "  ".join(fields))
    return len(records)


def _owned_containers(service: str | None = None) -> list[str]:
    command = [
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"label=com.docker.compose.project.working_dir={ROOT}",
    ]
    if service:
        command += ["--filter", f"label=com.docker.compose.service={service}"]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _raw_logs(service: str | None, *, tail: int, follow: bool) -> int:
    containers = _owned_containers(service)
    if containers:
        if follow and len(containers) != 1:
            print(
                "FOLLOW=1 requires SERVICE=<compose-service> when multiple containers exist.",
                file=sys.stderr,
            )
            return 2
        for container in containers:
            name = subprocess.run(
                ["docker", "inspect", "-f", "{{.Name}}", container],
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip().lstrip("/") or container
            print(f"== {name} ==")
            command = ["docker", "logs", "--tail", str(tail)]
            if follow:
                command.append("--follow")
            command.append(container)
            subprocess.run(command, cwd=ROOT, check=False)
        return 0

    app_files = sorted(LOCAL_LOGS.glob("*.log"))
    metal_files = sorted(NATIVE_METAL_LOGS.glob("*.log"))
    if service:
        files = [path for path in app_files if service in path.stem]
        if service in {"metal", "main-llm-vllm", "main_model"}:
            files += metal_files
    else:
        files = app_files + metal_files
    if not files:
        print("No matching project logs found.")
        return 0
    if follow:
        return subprocess.run(
            ["tail", "-n", str(tail), "-f", *map(str, files)],
            check=False,
        ).returncode
    for path in files:
        print(f"== {path.relative_to(ROOT)} ==")
        for line in _tail_lines(path, tail):
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read operator-relevant platform logs")
    parser.add_argument("--service")
    parser.add_argument("--tail", type=int, default=30)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument("--all-events", action="store_true")
    args = parser.parse_args(argv)
    if args.tail < 1:
        parser.error("--tail must be positive")
    if args.raw or args.service or args.follow:
        return _raw_logs(args.service, tail=args.tail, follow=args.follow)
    count = _structured_events(args.tail, all_events=args.all_events)
    if count == 0:
        print("No structured application events found.")
        print("Use make status for health, make logs ALL=1 for all request events, or RAW=1 for raw service output.")
    else:
        print("")
        print("For raw evidence: make logs SERVICE=<service> or make logs RAW=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
