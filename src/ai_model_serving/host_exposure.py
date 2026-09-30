from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_HOST_PUBLISHED_CATEGORIES = frozenset({"public_entrypoint", "visualization"})


def host_published_service_ids(
    services: Mapping[str, Any],
    *,
    include_visualization: bool = True,
) -> frozenset[str]:
    """Return service IDs that belong on the host boundary.

    services.yaml owns service roles. Public API entrypoints are always host-published.
    Visualization services are host-published only for targets that run the monitoring
    stack. Model runtimes, Risk Signal Service and operations backends remain internal.
    """
    result: set[str] = set()
    for service_id, raw in services.items():
        if not isinstance(raw, dict):
            continue
        categories = raw.get("categories")
        if not isinstance(categories, list):
            continue
        category_set = {str(item) for item in categories}
        if "public_entrypoint" in category_set:
            result.add(str(service_id))
        elif include_visualization and "visualization" in category_set:
            result.add(str(service_id))
    return frozenset(result)


def host_published_compose_services(
    services: Mapping[str, Any],
    *,
    include_visualization: bool = True,
) -> frozenset[str]:
    """Return canonical Compose service names for the host boundary."""
    service_ids = host_published_service_ids(
        services,
        include_visualization=include_visualization,
    )
    result: set[str] = set()
    for service_id in service_ids:
        raw = services.get(service_id)
        if not isinstance(raw, dict):
            continue
        compose_service = str(raw.get("compose_service", "")).strip()
        if compose_service:
            result.add(compose_service)
    return frozenset(result)
