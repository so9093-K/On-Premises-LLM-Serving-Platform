"""configs/services.yaml의 Compose 내부 service identity를 URL로 변환한다."""

from __future__ import annotations

from typing import Any


def _service(services: dict[str, Any], service_id: str) -> dict[str, Any]:
    try:
        service = services[service_id]
    except KeyError as exc:
        raise ValueError(f"configs/services.yaml is missing {service_id}") from exc
    if not isinstance(service, dict):
        raise ValueError(f"configs/services.yaml service {service_id!r} must be a mapping")
    return service


def _container_port(service: dict[str, Any]) -> int:
    try:
        return int(service["container_port"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("service registry entry requires numeric container_port") from exc


def internal_service_base_url(service: dict[str, Any], suffix: str = "") -> str:
    compose_service = str(service.get("compose_service", "")).strip()
    if not compose_service:
        raise ValueError("service registry entry requires compose_service")
    return f"http://{compose_service}:{_container_port(service)}{suffix}"


def internal_base_url(services: dict[str, Any], service_id: str, suffix: str = "") -> str:
    return internal_service_base_url(_service(services, service_id), suffix)
