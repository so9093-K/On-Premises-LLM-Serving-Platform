from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import ServiceError
from ..metrics import Metrics
from ..status import NOT_READY, READY, overall_readiness, readiness_phase

ReadinessEvaluator = Callable[[dict[str, Any]], tuple[str, str | None]]


def dependency_endpoint(base_url: str, path: str) -> str:
    """readiness 응답의 dependency endpoint 표기를 만든다.

    OpenAPI 예시(api_examples)도 같은 규칙을 써야 문서가 실제 응답과 어긋나지
    않으므로 join을 여기 한 곳에 둔다.
    """
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


@dataclass(frozen=True)
class DependencyProbe:
    name: str
    client: Any
    path: str
    headers: Mapping[str, str] | None = None
    evaluator: ReadinessEvaluator | None = None
    required: bool = True
    # Runtime을 호출하기 전에 이미 요청 불가로 확정된 사유다(예: 제어 Gate 차단).
    # 이 값이 있으면 Runtime 응답과 무관하게 not_ready이며, Runtime 자체의 미준비
    # 사유가 제어 계층의 차단 사유를 가리지 않는다.
    blocked_reason: str | None = None


async def collect_readiness(
    *,
    service: str,
    probes: list[DependencyProbe],
    metrics: Metrics | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """의존성 readiness를 확인하고 플랫폼 readiness 본문을 반환한다."""

    async def _probe_runtime(probe: DependencyProbe) -> tuple[str, str | None]:
        try:
            probe_json = getattr(probe.client, "probe_json", probe.client.get_json)
            coro = (
                probe_json(probe.path, headers=dict(probe.headers))
                if probe.headers is not None
                else probe_json(probe.path)
            )
            body = await asyncio.wait_for(coro, timeout=timeout_seconds)
            if probe.evaluator is not None:
                return probe.evaluator(body)
            return READY, None
        except TimeoutError:
            return NOT_READY, "READINESS_TIMEOUT"
        except ServiceError as exc:
            return NOT_READY, f"{exc.code}: {exc.message}"

    async def _probe_one(probe: DependencyProbe) -> dict[str, Any]:
        endpoint = dependency_endpoint(probe.client.endpoint.base_url, probe.path)
        if probe.blocked_reason is not None:
            status, message = NOT_READY, probe.blocked_reason
        else:
            status, message = await _probe_runtime(probe)
        if metrics is not None:
            metrics.record_readiness(probe.name, status == READY)
        item: dict[str, Any] = {"name": probe.name, "status": status, "endpoint": endpoint}
        if message:
            item["message"] = message
        return item

    dependencies: list[dict[str, Any]] = await asyncio.gather(*(_probe_one(p) for p in probes))

    required_statuses = [str(item["status"]) for item, probe in zip(dependencies, probes) if probe.required]
    overall = overall_readiness(required_statuses) if required_statuses else overall_readiness([])
    not_ready_dependencies = [item["name"] for item in dependencies if item["status"] != "ready"]
    required_not_ready = [
        item["name"] for item, probe in zip(dependencies, probes)
        if item["status"] != "ready" and probe.required
    ]
    optional_not_ready = [
        item["name"] for item, probe in zip(dependencies, probes)
        if item["status"] != "ready" and not probe.required
    ]
    if metrics is not None:
        metrics.record_overall_readiness(overall == READY)
    return {
        "status": overall,
        "service": service,
        "phase": readiness_phase(overall),
        "not_ready_dependencies": not_ready_dependencies,
        "required_not_ready_dependencies": required_not_ready,
        "optional_not_ready_dependencies": optional_not_ready,
        "dependencies": dependencies,
    }
