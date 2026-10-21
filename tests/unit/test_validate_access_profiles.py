from __future__ import annotations

from scripts.validation.validate_access_profiles import validate_services


def _gateway() -> dict[str, object]:
    return {
        "compose_service": "gateway",
        "container_port": 9400,
        "host_env_port": "GATEWAY_PORT",
        "default_host_port": 9400,
        "host_env_bind": "GATEWAY_BIND_ADDR",
        "default_bind": "0.0.0.0",
        "categories": ["gateway", "public_entrypoint", "host_process"],
    }


def test_internal_service_does_not_require_host_metadata() -> None:
    services = {
        "gateway": _gateway(),
        "prometheus": {
            "compose_service": "prometheus",
            "container_port": 9090,
            "categories": ["operations_endpoint", "metrics_backend"],
        },
    }

    assert validate_services(services) == []


def test_internal_service_rejects_host_projection_metadata() -> None:
    services = {
        "gateway": _gateway(),
        "prometheus": {
            "compose_service": "prometheus",
            "container_port": 9090,
            "host_env_port": "PROMETHEUS_PORT",
            "default_host_port": 9410,
            "host_env_bind": "PROMETHEUS_BIND_ADDR",
            "default_bind": "0.0.0.0",
            "categories": ["operations_endpoint", "metrics_backend"],
        },
    }

    violations = validate_services(services)

    assert any("must not define host port metadata" in item for item in violations)
    assert any("must not define host bind metadata" in item for item in violations)


def test_host_process_keeps_port_without_host_bind() -> None:
    services = {
        "gateway": _gateway(),
        "risk_signal_service": {
            "compose_service": "risk-signal-service",
            "container_port": 9405,
            "host_env_port": "RISK_SIGNAL_SERVICE_PORT",
            "default_host_port": 9405,
            "categories": ["risk_signal_service", "host_process"],
        },
    }

    assert validate_services(services) == []
