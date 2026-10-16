from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
_COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def require_compose_project(project: str) -> str:
    """Compose 프로젝트 이름을 정규화하고 유효하지 않으면 거부한다.

    Docker 생명주기 변경은 프로젝트·서비스 범위 검색에서 서비스 이름만 사용하는
    검색으로 축소해서는 안 된다. 동일한 Docker 호스트에서 여러 Compose 프로젝트가
    서비스 Label을 공유할 수 있어, 프로젝트 누락 시 다른 배포까지 제어 범위가 넓어진다.
    """
    normalized = project.strip()
    if not normalized:
        raise RuntimeError(
            "COMPOSE_PROJECT is required before Runtime Controller Docker access"
        )
    return normalized


def compose_container_filter(project: str, service: str | None = None) -> str:
    normalized_project = require_compose_project(project)
    labels = [f"{_COMPOSE_PROJECT_LABEL}={normalized_project}"]
    if service is not None:
        normalized_service = service.strip()
        if not normalized_service:
            raise RuntimeError("Compose service scope must be non-empty")
        labels.append(f"{_COMPOSE_SERVICE_LABEL}={normalized_service}")
    return json.dumps({"label": labels})


def scoped_container_id(
    row: object,
    *,
    project: str,
    service: str | None = None,
) -> str:
    """Docker 조회 결과 한 건이 지정된 Compose 프로젝트·서비스에 속하는지 검증한다."""
    normalized_project = require_compose_project(project)
    if not isinstance(row, Mapping):
        raise RuntimeError("Docker container row must be an object")
    labels = row.get("Labels")
    if not isinstance(labels, Mapping):
        raise RuntimeError("Docker container row is missing Compose labels")
    actual_project = str(labels.get(_COMPOSE_PROJECT_LABEL) or "")
    if actual_project != normalized_project:
        raise RuntimeError(
            "Docker container escaped Compose project scope: "
            f"expected {normalized_project!r}, got {actual_project!r}"
        )
    if service is not None:
        normalized_service = service.strip()
        actual_service = str(labels.get(_COMPOSE_SERVICE_LABEL) or "")
        if actual_service != normalized_service:
            raise RuntimeError(
                "Docker container escaped Compose service scope: "
                f"expected {normalized_service!r}, got {actual_service!r}"
            )
    container_id = str(row.get("Id") or "")
    if not container_id:
        raise RuntimeError("Docker container row is missing Id")
    return container_id


def one_scoped_container_row(
    rows: object,
    *,
    project: str,
    service: str,
) -> Mapping[str, Any] | None:
    if not isinstance(rows, list):
        raise RuntimeError("Docker container listing must be a list")
    if any(not isinstance(row, Mapping) for row in rows):
        raise RuntimeError("Docker container listing contains a non-object row")
    if len(rows) > 1:
        raise RuntimeError(
            f"multiple containers found for scoped service {service!r} "
            f"in Compose project {require_compose_project(project)!r}: {len(rows)}"
        )
    if not rows:
        return None
    row = rows[0]
    scoped_container_id(row, project=project, service=service)
    return row

