"""Run exact checked-in Runtime dashboard queries against a disposable real Loki.

Synthetic input proves selector behavior, NOT operational GPU/MLX telemetry.
Only loopback Loki is queried. No request/response secrets are recorded.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:3100"
PANELS = (
    "런타임 HTTP 오류 (vLLM·MLX, 텍스트 파싱)",
    "런타임 원본 로그",
    "엔진 크래시·Traceback (텍스트 검색)",
)


def api(path: str, data: dict | None = None) -> dict:
    payload = None if data is None else json.dumps(data).encode("utf-8")
    request = Request(
        URL + path,
        data=payload,
        headers={"Content-Type": "application/json"} if payload else {},
    )
    with urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else {}


def wait_ready() -> None:
    for attempt in range(60):
        try:
            with urlopen(URL + "/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Loki did not become ready within 60 seconds")


def main() -> None:
    wait_ready()
    now = time.time_ns()
    message = 'INFO:     127.0.0.1:19401 - "GET /ready HTTP/1.1" 503 Service Unavailable'
    streams = [
        ({"job": "docker", "service": "main-llm-vllm"}, ["Traceback Runtime docker", message]),
        ({"job": "native"}, ["Traceback Runtime native", message]),
        ({"job": "docker", "service": "grafana"}, ["Traceback MONITORING grafana", message]),
        ({"job": "docker", "service": "prometheus"}, ["Traceback MONITORING prometheus", message]),
        ({"job": "docker"}, ["Traceback MONITORING unlabeled docker", message]),
    ]
    api("/loki/api/v1/push", {
        "streams": [
            {"stream": labels, "values": [[str(now - 30_000_000_000 + i * 1_000_000), line] for i, line in enumerate(lines)]}
            for labels, lines in streams
        ]
    })
    dashboard = json.loads((ROOT / "ops/grafana/dashboards/request_log_explorer.json").read_text(encoding="utf-8"))
    for title in PANELS:
        panel = next(item for item in dashboard["panels"] if item["title"] == title)
        expected = '"GET /ready' if title.startswith("런타임 HTTP") else "Traceback"
        for job in ("docker", "native"):
            target = next(item for item in panel["targets"] if item["refId"] == ("A" if job == "docker" else "B"))
            query = target["expr"].replace("${search_text}", ".*")
            params = urlencode({
                "query": query,
                "start": str(now - 70_000_000_000),
                "end": str(now + 10_000_000_000),
                "limit": 100,
                "direction": "backward",
            })
            found: list[str] = []
            for _ in range(15):
                response = api("/loki/api/v1/query_range?" + params)
                assert response["status"] == "success", (title, job, response)
                found = [line for result in response["data"]["result"] for _, line in result["values"]]
                if any(expected in line for line in found):
                    break
                time.sleep(1)
            assert any(expected in line for line in found), (title, job, found)
            assert all("MONITORING" not in line for line in found), (title, job, found)
            if job == "docker":
                assert any("Runtime docker" in line or "19401" in line for line in found), title
            else:
                assert any("Runtime native" in line or "19401" in line for line in found), title
            print(f"PASS {title} {job}: {len(found)} runtime records; monitoring log excluded")
    print("PASS actual Loki query_range smoke using synthetic Docker + native logs")


if __name__ == "__main__":
    main()
