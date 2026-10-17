"""Dashboard LogQL selectors must follow the canonical model-runtime service registry.

These checks protect the ingestion/query boundary; an optional Loki-backed smoke
test executes the exact selectors against running Loki (no production credentials).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "ops/grafana/dashboards/request_log_explorer.json"
REGISTRY = ROOT / "configs/services.yaml"

RUNTIME_TITLES = (
    "런타임 HTTP 오류 (vLLM·MLX, 텍스트 파싱)",
    "런타임 원본 로그",
    "엔진 크래시·Traceback (텍스트 검색)",
)


def _runtime_services() -> set[str]:
    services = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["services"]
    return {
        definition["compose_service"]
        for definition in services.values()
        if "model_runtime" in definition.get("categories", ())
    }


def test_runtime_log_panels_use_exact_registry_services_and_native_job() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    for title in RUNTIME_TITLES:
        panel = next(panel for panel in dashboard["panels"] if panel["title"] == title)
        assert len(panel["targets"]) == 2, title
        docker, native = (target["expr"] for target in panel["targets"])
        match = re.search(r'\{job="docker",service=~"([^"]+)"\}', docker)
        assert match is not None, title
        allowed = set(match.group(1).split("|"))
        assert allowed == _runtime_services(), title
        assert '{job="native"}' in native, title
        assert "service=" not in native, title
        assert not any(service in allowed for service in ("grafana", "loki", "gateway", "prometheus"))
        assert "job=~" not in docker + native
        assert "refId" in panel["targets"][0] and panel["targets"][1]["refId"] == "B"

        if title.startswith("런타임 HTTP"):
            # Organize needs one frame. The Docker and native query frames
            # must be merged before organizing the table columns.
            transforms = [transform["id"] for transform in panel["transformations"]]
            assert transforms == ["extractFields", "merge", "organize"], transforms


def test_runtime_queries_do_not_claim_gateway_overlap() -> None:
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    runtime_errors = next(panel for panel in dashboard["panels"] if panel["title"] == RUNTIME_TITLES[0])
    assert "Gateway 로그는 별도" in runtime_errors["description"]


def test_metal_overview_preserves_shared_metrics_and_links_to_provisioned_dashboards() -> None:
    from scripts.render_runtime_assets import render_macos_dashboard

    shared = json.loads((ROOT / "ops/grafana/dashboards/service_overview.json").read_text(encoding="utf-8"))
    metal = json.loads(render_macos_dashboard(ROOT, "service_overview"))
    assert metal["uid"] == shared["uid"]
    assert metal["panels"] == shared["panels"]
    # Static Metal은 GPU 용량·오늘 사용량 Dashboard를 Provision하지 않는다.
    assert [link["url"] for link in metal["links"]] == ["/d/request_log_explorer"]
    assert {link["url"] for link in shared["links"]} >= {
        "/d/gpu_capacity_and_oom_risk", "/d/usage_today",
    }
    explorer = json.loads(render_macos_dashboard(ROOT, "request_log_explorer"))
    assert [link["url"] for link in explorer["links"] if link["url"].startswith("/d/")] == ["/d/service_overview"]
