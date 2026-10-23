"""Grafana 집계→요청 로그 이동은 조회 시간과 경로 맥락을 보존한다."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARDS = ROOT / "ops" / "grafana" / "dashboards"


def test_api_route_usage_links_to_matching_gateway_logs() -> None:
    usage = json.loads((DASHBOARDS / "usage_today.json").read_text(encoding="utf-8"))
    logs = json.loads((DASHBOARDS / "request_log_explorer.json").read_text(encoding="utf-8"))

    route_panel = next(item for item in usage["panels"] if item["id"] == 2)
    link = next(
        item for item in route_panel["fieldConfig"]["defaults"]["links"]
        if item["title"] == "이 경로의 요청 로그 보기"
    )
    assert "/d/request_log_explorer?" in link["url"]
    assert "from=${__from}" in link["url"]
    assert "to=${__to}" in link["url"]
    assert "var-service=gateway" in link["url"]
    assert "var-route_filter=^${__field.labels.route}$" in link["url"]

    variables = {item["name"] for item in logs["templating"]["list"]}
    assert {"route_filter", "service"} <= variables
    request_panel = next(item for item in logs["panels"] if item["id"] == 1)
    assert 'route=~"${route_filter}"' in request_panel["targets"][0]["expr"]
