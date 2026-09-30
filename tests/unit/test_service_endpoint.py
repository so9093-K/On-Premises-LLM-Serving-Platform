from __future__ import annotations

import pytest

from scripts.lib.service_endpoint import (
    internal_base_url,
    internal_service_base_url,
    published_base_url,
)


def _services() -> dict[str, dict[str, object]]:
    return {
        "prometheus": {
            "compose_service": "prometheus",
            "container_port": 9090,
            "host_env_port": "PROMETHEUS_PORT",
            "default_host_port": 9410,
            "host_env_bind": "PROMETHEUS_BIND_ADDR",
            "default_bind": "0.0.0.0",
        }
    }


def test_internal_base_url_uses_compose_service_and_container_port() -> None:
    services = _services()

    assert internal_base_url(services, "prometheus") == "http://prometheus:9090"
    assert internal_base_url(services, "prometheus", "/api/v1") == "http://prometheus:9090/api/v1"
    assert internal_service_base_url(services["prometheus"], "/metrics") == "http://prometheus:9090/metrics"


def test_published_base_url_keeps_host_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    services = _services()
    monkeypatch.setenv("PROMETHEUS_BIND_ADDR", "0.0.0.0")
    monkeypatch.setenv("PROMETHEUS_PORT", "9510")

    assert published_base_url(services, "prometheus") == "http://localhost:9510"


def test_internal_base_url_requires_compose_identity() -> None:
    services = {"broken": {"container_port": 9400}}

    with pytest.raises(ValueError, match="compose_service"):
        internal_base_url(services, "broken")
