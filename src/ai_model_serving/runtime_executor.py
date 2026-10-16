"""Docker 컨테이너 신원을 외부에 노출하지 않는 제한된 Runtime 실행 어댑터.

배치·Admission·검토된 작업·복구는 Runtime Controller가 소유한다.
이 로컬 Executor만 허용된 Compose 서비스를 Docker ID로 해석한다.
다른 호스트에 적용하려면 인증·Fencing을 갖춘 별도 Executor가 필요하며,
여기서는 원격 Docker Socket 접근 권한을 부여하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from .docker_scope import (
    compose_container_filter,
    one_scoped_container_row,
    require_compose_project,
    scoped_container_id,
)


class RuntimeExecutor(Protocol):
    async def status(self, service: str) -> str: ...
    async def start(self, service: str) -> bool: ...
    async def stop(self, service: str) -> bool: ...


@dataclass(frozen=True)
class DockerRuntimeExecutor:
    docker_socket: str
    compose_project: str
    allowed_services: frozenset[str]
    status_only_services: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        require_compose_project(self.compose_project)
        if not self.allowed_services or not all(self.allowed_services):
            raise ValueError("runtime executor requires non-empty allowlisted services")

    def _check(self, service: str, *, mutate: bool) -> None:
        authorized = self.allowed_services if mutate else self.allowed_services | self.status_only_services
        if service not in authorized:
            raise ValueError(f"runtime executor service not allowlisted: {service}")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=self.docker_socket),
            base_url="http://docker",
        )

    async def _lookup(self, service: str, *, mutate: bool) -> tuple[str, str] | None:
        self._check(service, mutate=mutate)
        async with self._client() as client:
            response = await client.get(
                "/containers/json",
                params={"all": "true", "filters": compose_container_filter(self.compose_project, service)},
                timeout=5.0,
            )
            response.raise_for_status()
            row = one_scoped_container_row(
                response.json(), project=self.compose_project, service=service
            )
            if row is None:
                return None
            return scoped_container_id(row, project=self.compose_project, service=service), str(
                row.get("State") or "unknown"
            )

    async def status(self, service: str) -> str:
        row = await self._lookup(service, mutate=False)
        return row[1] if row is not None else "not_found"

    async def _mutate(self, service: str, action: str) -> bool:
        row = await self._lookup(service, mutate=True)
        if row is None:
            return False
        container_id, _ = row
        async with self._client() as client:
            response = await client.post(f"/containers/{container_id}/{action}", timeout=30.0)
            if response.status_code not in (204, 304):
                response.raise_for_status()
        return True

    async def start(self, service: str) -> bool:
        return await self._mutate(service, "start")

    async def stop(self, service: str) -> bool:
        return await self._mutate(service, "stop")
