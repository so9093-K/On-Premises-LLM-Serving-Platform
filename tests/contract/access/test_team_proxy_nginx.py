"""팀원 진입점의 허용·차단 계약을 실제 Nginx를 통해 검증한다."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

CONFIG = Path(__file__).resolve().parents[3] / "ops" / "access" / "team-api.nginx.conf"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StubGateway(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.respond()

    def do_POST(self):  # noqa: N802
        self.respond()

    def do_DELETE(self):  # noqa: N802
        self.respond()

    def respond(self):
        if self.headers.get("Authorization") != "Bearer demo-public-api-key":
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"path": self.path, "method": self.command, "auth": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    if not shutil.which("nginx"):
        pytest.skip("nginx 실행 파일이 없어 실제 프록시 테스트를 실행할 수 없음")
    tmp = tmp_path_factory.mktemp("team-proxy")
    gateway_port = free_port()
    team_port = free_port()
    upstream = ThreadingHTTPServer(("127.0.0.1", gateway_port), StubGateway)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    conf = (CONFIG.read_text(encoding="utf-8")
            .replace("127.0.0.1:9480", f"127.0.0.1:{team_port}")
            .replace("127.0.0.1:9400", f"127.0.0.1:{gateway_port}"))
    (tmp / "team.conf").write_text(conf, encoding="utf-8")
    (tmp / "nginx.conf").write_text(
        f"worker_processes 1;\npid {tmp}/nginx.pid;\nerror_log {tmp}/error.log;\n"
        f"events {{ worker_connections 128; }}\nhttp {{ include {tmp}/team.conf; }}\n",
        encoding="utf-8",
    )
    test = subprocess.run(["nginx", "-t", "-p", str(tmp), "-c", str(tmp / "nginx.conf")],
                          capture_output=True, text=True, check=False)
    assert test.returncode == 0, test.stderr
    process = subprocess.Popen(["nginx", "-g", "daemon off;", "-p", str(tmp),
                                "-c", str(tmp / "nginx.conf")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError(f"nginx exited early: {process.stderr.read().decode()}")
            try:
                with socket.create_connection(("127.0.0.1", team_port), timeout=.1):
                    break
            except OSError:
                time.sleep(.02)
        else:
            raise AssertionError("nginx team port did not start")
        yield f"http://127.0.0.1:{team_port}"
    finally:
        process.terminate()
        process.wait(timeout=10)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def request(base: str, path: str, method: str = "GET", key: str | None = None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = b"{}" if method == "POST" else None
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=3) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()


@pytest.mark.parametrize(("path", "method"), [
    ("/v1/models", "GET"),
    ("/v1/chat/completions", "POST"),
    ("/v1/responses", "POST"),
    ("/v1/embeddings", "POST"),
])
def test_api_only_forwards_allowed_routes_with_api_key(proxy, path, method):
    status, body = request(proxy, path, method, "demo-public-api-key")
    assert status == 200
    assert json.loads(body) == {"path": path, "method": method, "auth": True}
    assert request(proxy, path, method)[0] == 401


@pytest.mark.parametrize("path", [
    "/admin/console/", "/admin/configuration", "/internal/status",
    "/ready", "/metrics", "/docs", "/openapi.json", "/",
    "/v1/models/", "/v1/chat/completions/extra",
    "/v1/%6dodels", "/v1/chat%2fcompletions", "/v1/models%2f..%2fadmin",
])
def test_other_or_encoded_paths_are_denied_even_with_admin_key(proxy, path):
    status, _ = request(proxy, path, key="demo-public-api-key")
    assert status != 200


@pytest.mark.parametrize(("path", "method"), [
    ("/v1/models", "POST"), ("/v1/models", "DELETE"),
    ("/v1/chat/completions", "GET"), ("/v1/responses", "GET"),
])
def test_unexpected_method_is_denied(proxy, path, method):
    status, _ = request(proxy, path, method, "demo-public-api-key")
    assert status == 405
