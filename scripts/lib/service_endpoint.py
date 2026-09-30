"""configs/services.yaml의 publish 주소를 host에서 접속 가능한 URL로 바꾼다.

services.yaml이 주소를 소유하고, runtime validation은 여기서만 그 주소를 해석한다.
"""
from __future__ import annotations

import os
from typing import Any

# Compose의 wildcard bind는 listen 주소이지 접속 대상이 아니다.
_WILDCARD_BINDS = {"0.0.0.0", "::", "[::]"}


def _published_host(service: dict[str, Any]) -> str:
    bind_key = str(service.get("host_env_bind", ""))
    bind = os.getenv(bind_key, "").strip()
    return bind if bind and bind not in _WILDCARD_BINDS else "localhost"


def _published_port(service: dict[str, Any]) -> int:
    """운영자가 port를 바꿔 띄웠으면 그 port로 접속해야 한다."""
    port_key = str(service.get("host_env_port", ""))
    override = os.getenv(port_key, "").strip()
    if override:
        try:
            return int(override)
        except ValueError as exc:
            raise ValueError(f"{service.get('host_env_port')}={override!r} is not a port number") from exc
    try:
        return int(service["default_host_port"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("service registry entry requires default_host_port") from exc


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


def published_base_url(services: dict[str, Any], service_id: str, suffix: str = "") -> str:
    return service_base_url(_service(services, service_id), suffix)


def service_base_url(service: dict[str, Any], suffix: str = "") -> str:
    return f"http://{_published_host(service)}:{_published_port(service)}{suffix}"
