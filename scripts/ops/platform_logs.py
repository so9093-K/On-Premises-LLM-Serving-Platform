#!/usr/bin/env python3
"""운영자에게 필요한 요약 로그를 제공한다.

기본 출력은 구조화된 애플리케이션 이벤트다. 원시 컨테이너·프로세스 로그는
운영자가 명시적으로 요청할 때 제공하여 진단 증거를 보존하면서도
일반 터미널 출력에 과도한 로그가 쌓이지 않도록 한다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ops.compose_ownership import owned_container_ids  # noqa: E402
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
    records: list[dict[str, object]] = []
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

    # 한 서비스의 반복 scrape 오류가 다른 서비스의 준비 실패를 밀어내지 않게 한다.
    # ALL=1은 요청별 증거를 그대로 보여 주고 기본 요약만 같은 원인을 묶는다.
    if all_events:
        selected = [(event, 1) for event in records[-limit:]]
    else:
        groups: dict[tuple[str, ...], tuple[dict[str, object], int]] = {}
        for event in records:
            key = tuple(str(event.get(field) or "") for field in (
                "service", "route", "event", "status_code", "error_code", "diagnostic_code", "readiness_summary",
            ))
            previous = groups.pop(key, None)
            groups[key] = (event, previous[1] + 1 if previous else 1)
        selected = list(groups.values())[-limit:]
    print("Recent application events" if all_events else "Recent error and readiness events")
    for event, count in selected:
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
        if event.get("readiness_summary"):
            fields.append(f"dependency={event['readiness_summary']}")
        if count > 1:
            fields.append(f"repeated={count}")
        if request_id:
            fields.append(f"request={request_id}")
        print("  " + "  ".join(fields))
    return len(selected)


def _owned_containers(service: str | None = None) -> list[str]:
    try:
        return owned_container_ids(ROOT, service)
    except (OSError, RuntimeError):
        return []


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
