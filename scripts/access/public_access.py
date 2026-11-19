#!/usr/bin/env python3
"""Checkout 소유 사용자 Proxy와 Funnel 8443의 생명주기를 관리한다."""
from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

PUBLIC_PORT = 8443


def sharing_enabled(values: dict[str, str], override: str | None, access: str | None) -> bool:
    if override is not None:
        enabled = override == "on"
    elif access is not None:
        enabled = access == "edge"
    else:
        raw = values.get("PUBLIC_ACCESS_ENABLED", "true").lower()
        if raw not in {"true", "false"}:
            raise ValueError("PUBLIC_ACCESS_ENABLED는 true 또는 false여야 합니다.")
        enabled = raw == "true"
    if enabled and access not in {None, "edge"}:
        raise ValueError("외부 공유에는 ACCESS=edge가 필요합니다. 로컬 실행은 SHARE=off를 사용하세요.")
    return enabled


def _run(*command: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{command[0]} 실행 실패")
    return result.stdout


def _json_command(*command: str) -> dict:
    value = json.loads(_run(*command))
    if not isinstance(value, dict):
        raise RuntimeError("Tailscale 상태 응답을 읽을 수 없습니다.")
    return value


def listener_present(config: dict, port: int = PUBLIC_PORT) -> bool:
    if str(port) in config.get("TCP", {}):
        return True
    if any(key.endswith(f":{port}") for key in config.get("Web", {})):
        return True
    return any(listener_present(child, port) for group in ("Foreground", "Services")
               for child in config.get(group, {}).values())


def owns_listener(config: dict, owner: dict) -> bool:
    """저장된 체크아웃 정보와 현재 단일 HTTPS Handler가 모두 일치해야 한다."""
    key = owner["host_port"]
    expected = {"Handlers": {"/": {"Proxy": owner["target"]}}}
    web = {name: value for name, value in config.get("Web", {}).items() if name.endswith(f":{PUBLIC_PORT}")}
    return (
        owner.get("checkout") == str(ROOT)
        and web == {key: expected}
        and config.get("TCP", {}).get(str(PUBLIC_PORT)) == {"HTTPS": True}
        and config.get("AllowFunnel", {}).get(key) is True
        and not any(listener_present(child) for group in ("Foreground", "Services")
                    for child in config.get(group, {}).values())
    )


def _owner(directory: Path) -> dict | None:
    path = directory / "owner.json"
    if not path.exists():
        return None
    owner = json.loads(path.read_text())
    if (not isinstance(owner, dict) or owner.get("checkout") != str(ROOT)
        or not all(isinstance(owner.get(key), str) for key in ("host_port", "target"))):
        raise RuntimeError("외부 공유의 체크아웃 소유권을 확인할 수 없습니다.")
    return owner


def _nginx_owned(directory: Path) -> bool:
    pid_file = directory / "nginx.pid"
    try:
        pid = pid_file.read_text().strip()
    except FileNotFoundError:
        return False
    if not pid.isdecimal() or int(pid) < 2:
        raise RuntimeError("사용자 Proxy PID가 유효하지 않습니다.")
    result = subprocess.run(["ps", "-ww", "-p", pid, "-o", "command="], text=True, capture_output=True)
    if result.returncode or not pid_file.exists():
        pid_file.unlink(missing_ok=True)
        return False
    if ("nginx: master process" not in result.stdout
        or not result.stdout.rstrip().endswith(f"-c {directory / 'nginx.conf'}")):
        raise RuntimeError("사용자 Proxy PID의 프로세스 소유권이 일치하지 않습니다.")
    return True


def stop(directory: Path) -> None:
    owner = _owner(directory)
    if owner:
        config = _json_command("tailscale", "funnel", "status", "--json")
        if listener_present(config):
            if not owns_listener(config, owner):
                raise RuntimeError("8443 설정이 변경되어 자동 해제하지 않았습니다. tailscale funnel status를 확인하세요.")
            _run("tailscale", "funnel", "--https=8443", "off")
            if listener_present(_json_command("tailscale", "funnel", "status", "--json")):
                raise RuntimeError("Funnel 8443 해제를 확인하지 못했습니다.")
    if _nginx_owned(directory):
        _run("nginx", "-p", f"{directory}/", "-c", str(directory / "nginx.conf"), "-s", "stop")
        deadline = time.monotonic() + 5
        while _nginx_owned(directory):
            if time.monotonic() >= deadline:
                raise RuntimeError("사용자 Proxy 종료를 확인하지 못했습니다.")
            time.sleep(0.1)
    if owner:
        (directory / "owner.json").unlink()


def start(env_file: Path, directory: Path) -> str:
    from ai_model_serving.port_namespace import load_port_namespace
    from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file
    from scripts.access.remote_access import nginx_config, preflight

    issues = preflight(env_file)
    if issues:
        raise RuntimeError("; ".join(issues))
    missing = [name for name in ("nginx", "tailscale") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"서버 도구 설치 필요: {', '.join(missing)}. docs/guides/public-access.md 참고")
    status = _json_command("tailscale", "status", "--json")
    if status.get("BackendState") != "Running":
        raise RuntimeError("서버 운영자의 Tailscale 연결이 필요합니다: sudo tailscale up")
    hostname = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if not hostname or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for char in hostname):
        raise RuntimeError("Tailscale HTTPS 호스트 이름을 확인할 수 없습니다.")
    config = _json_command("tailscale", "funnel", "status", "--json")
    owner = _owner(directory)
    if listener_present(config) and (owner is None or not owns_listener(config, owner)):
        raise RuntimeError("기존 Serve/Funnel 8443을 보존했습니다. 해당 Listener를 먼저 운영자가 해제해야 합니다.")
    stop(directory)
    values = load_strict_env_file(env_file)
    listener = load_port_namespace(ROOT, values).port("team_api_proxy")
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", listener))
    for name in ("proxy-temp", "body-temp", "fastcgi-temp", "uwsgi-temp", "scgi-temp"):
        (directory / name).mkdir(exist_ok=True)
    def quote(path: Path) -> str:
        return json.dumps(str(path), ensure_ascii=False)
    configuration = (
        f"worker_processes 1;\npid {quote(directory / 'nginx.pid')};\n"
        f"error_log {quote(directory / 'error.log')} warn;\n"
        "events { worker_connections 256; }\nhttp {\naccess_log off;\n"
        f"proxy_temp_path {quote(directory / 'proxy-temp')};\n"
        f"client_body_temp_path {quote(directory / 'body-temp')};\n"
        f"fastcgi_temp_path {quote(directory / 'fastcgi-temp')};\n"
        f"uwsgi_temp_path {quote(directory / 'uwsgi-temp')};\n"
        f"scgi_temp_path {quote(directory / 'scgi-temp')};\n"
        + nginx_config(env_file, public=True) + "\n}\n"
    )
    config_path = directory / "nginx.conf"
    config_path.write_text(configuration)
    _run("nginx", "-p", f"{directory}/", "-c", str(config_path), "-t")
    _run("nginx", "-p", f"{directory}/", "-c", str(config_path))
    owner = {"checkout": str(ROOT), "host_port": f"{hostname}:8443", "target": f"http://127.0.0.1:{listener}"}
    try:
        (directory / "owner.json").write_text(json.dumps(owner))
        verify_proxy(listener, values)
        _run("tailscale", "funnel", "--yes", "--bg", "--https=8443", owner["target"])
        if not owns_listener(_json_command("tailscale", "funnel", "status", "--json"), owner):
            raise RuntimeError("Funnel 8443의 공개 대상 확인에 실패했습니다.")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        # 공개 상태를 확인할 수 없어도 upstream을 먼저 닫아 요청 전달을 중단한다.
        if _nginx_owned(directory):
            _run("nginx", "-p", f"{directory}/", "-c", str(config_path), "-s", "stop")
        raise
    return f"https://{hostname}:8443"


def verify_proxy(listener: int, values: dict[str, str]) -> None:
    """공개하기 전에 실제 Proxy의 관리 경로 차단·사용자 인증을 확인한다."""
    def get(path: str, key: str | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(f"http://127.0.0.1:{listener}{path}")
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    for path in ("/admin/console/", "/admin/config/schema", "/ready", "/metrics", "/internal/main-model/drain-status"):
        if get(path)[0] != 404:
            raise RuntimeError("사용자 Proxy의 운영 경로 차단을 확인하지 못했습니다.")
    if get("/playground/config.json")[0] != 401 or get("/v1/models")[0] != 401:
        raise RuntimeError("실행 중 Gateway가 사용자 API 인증을 요구하지 않습니다.")
    key = values["API_KEYS"].split(",", 1)[0].strip()
    code, payload = get("/playground/config.json", key)
    if code != 200 or not isinstance(json.loads(payload).get("features"), list):
        raise RuntimeError("사용자 API 키로 Playground에 연결하지 못했습니다.")
    if get("/playground/")[0] != 200:
        raise RuntimeError("사용자 Playground 화면이 준비되지 않았습니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "status"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    directory = ROOT / ".runtime/public-access"
    if args.command == "down" and not directory.exists():
        return 0
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with (directory / "lifecycle.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.command == "up":
                url = start(args.env_file, directory)
                print(f"[platform] External READY  {url}/playground/")
                print(f"[platform] API Base URL   {url}/v1 · 사용자 API 키 필요")
            elif args.command == "down":
                stop(directory)
            else:
                owner = _owner(directory)
                if owner and _nginx_owned(directory) and owns_listener(
                    _json_command("tailscale", "funnel", "status", "--json"), owner,
                ):
                    print(f"External      READY  https://{owner['host_port']}/playground/")
                else:
                    print("External      UNAVAILABLE · make up으로 연결 준비")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"[platform] External UNAVAILABLE · {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
