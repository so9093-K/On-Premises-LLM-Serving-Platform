from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...app_kernel import readiness_response
from ...errors import ServiceError
from ...logging_policy import record_readiness_failure
from ..endpoint_spec import GATEWAY_ENDPOINTS
from ...api_examples import loading_response_example, ready_response_example
from ...services.readiness import DependencyProbe, collect_readiness
from ...services.runtime_state import RuntimeState
from ...status import NOT_READY, READY
from ...services.runtime_controller_client import (
    RuntimeControllerRequestError,
    RuntimeControllerUnavailableError,
)
from ..error_responses import (
    runtime_controller_request_error_response,
    runtime_controller_unavailable_response,
)

_GW = {(s.method, s.path): s for s in GATEWAY_ENDPOINTS}


def _risk_signal_service_readiness(body: dict[str, Any]) -> tuple[str, str | None]:
    status = READY if body.get("status") == READY else NOT_READY
    if status == READY:
        return status, None
    waiting = [
        item.get("name")
        for item in body.get("dependencies", [])
        if isinstance(item, dict) and item.get("status") != "ready"
    ]
    message = (
        "waiting for Risk Signal Service dependencies: " + ", ".join(str(item) for item in waiting)
        if waiting
        else "Risk Signal Service is not ready"
    )
    return status, message


async def _readiness(
    clients: Any,
    settings: Any,
    metrics: Any = None,
    *,
    admin_token: str | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    runtime_clients = getattr(clients, "runtime_clients_by_service_key", None)
    if runtime_clients is None:
        runtime_clients = getattr(clients, "runtimes", {})
    runtime_state = getattr(clients, "runtime_state", None)

    async def runtime_required(service_key: str) -> bool:
        if service_key not in settings.required_runtime_keys:
            return False
        if runtime_state is None:
            return True
        state = await runtime_state.get(service_key)
        return state != RuntimeState.stopped

    embedding_probes: list[DependencyProbe] = []
    seen_service_keys: set[str] = set()
    for profile in settings.embedding_profiles.values():
        service_key = profile.service_key
        if service_key in seen_service_keys:
            continue
        seen_service_keys.add(service_key)
        client = getattr(clients, service_key, None)
        if client is None and isinstance(runtime_clients, dict):
            client = runtime_clients.get(service_key)
        if client is not None:
            embedding_probes.append(
                DependencyProbe(
                    settings.runtime_service_id(service_key),
                    client,
                    "models",
                    required=await runtime_required(service_key),
                )
            )
    # 의존성 이름은 configs/runtime_topology.yaml이 선언한 service_id다. 코드에서
    # 조립하면(예전엔 main_llm에 문자열을 직접 박고 embedding은 f"{key}_vllm"였다)
    # 선언된 식별자와 갈라지고, /ready만 옛 이름을 계속 광고하게 된다.
    probes = [
        DependencyProbe(
            settings.runtime_service_id("main_llm"),
            clients.main_llm,
            "models",
            required=await runtime_required("main_llm"),
        ),
        *embedding_probes,
    ]
    risk_signal_service = getattr(clients, "risk_signal_service", None)
    if settings.feature_enabled("risk") and risk_signal_service is not None:
        probes.append(
            DependencyProbe(
                "risk-signal-service",
                risk_signal_service,
                "/ready",
                {"authorization": f"Bearer {admin_token}"} if admin_token else None,
                _risk_signal_service_readiness,
                required=True,
            )
        )
    return await collect_readiness(service="gateway", probes=probes, metrics=metrics, timeout_seconds=timeout_seconds)


def build_router(admin_dependencies: list, clients: Any, metrics: Any, settings: Any) -> APIRouter:
    router = APIRouter()

    _s = _GW[("GET", "/ready")]

    @router.get(
        "/ready",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {
                "description": "모든 dependency 준비 완료",
                "content": {"application/json": {"example": ready_response_example()}},
            },
            401: {"description": "Admin Bearer token 필요"},
            503: {
                "description": "일부 dependency 로딩 중 또는 불가",
                "content": {"application/json": {"example": loading_response_example()}},
            },
        },
    )
    async def ready(request: Request) -> JSONResponse:
        admin_token = next(iter(settings.security.admin_api_keys), None)
        body = await _readiness(
            clients,
            settings,
            metrics,
            admin_token=admin_token,
            timeout_seconds=settings.readiness_probe_timeout_seconds,
        )
        record_readiness_failure(request, body)
        return readiness_response(body)

    _s = _GW[("GET", "/admin/serving-envelope")]

    @router.get(
        "/admin/serving-envelope",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {"description": "현재 Main Model의 resolved admission과 engine serving context"},
            401: {"description": "Admin Bearer token 필요"},
            503: {"description": "Dynamic target에서 active profile 또는 Runtime Controller 상태를 확인할 수 없음"},
        },
    )
    async def serving_envelope() -> JSONResponse:
        main_endpoint = settings.runtime("main_llm")
        target = settings.deployment_target

        if target.control_mode == "runtime_controller":
            runtime_controller = getattr(clients, "runtime_controller", None)
            if runtime_controller is None:
                raise ServiceError(
                    "MAIN_MODEL_CONTROL_UNAVAILABLE",
                    "Runtime Controller is not configured",
                    retry_after_seconds=5,
                )
            try:
                snapshot = await runtime_controller.main_model(observed=False)
            except RuntimeControllerRequestError as exc:
                return runtime_controller_request_error_response(exc)
            except RuntimeControllerUnavailableError as exc:
                return runtime_controller_unavailable_response(exc)
            active_profile = snapshot.get("active_profile")
            engine_policy = snapshot.get("engine_policy")
            if not isinstance(active_profile, dict) or not active_profile.get("id"):
                raise ServiceError(
                    "MODEL_UNAVAILABLE",
                    "Main Model has no active profile for serving-envelope projection.",
                    retry_after_seconds=5,
                )
            if not isinstance(engine_policy, dict) or not engine_policy:
                raise ServiceError(
                    "MAIN_MODEL_CONTROL_UNAVAILABLE",
                    "Runtime Controller did not provide the resolved Main Model engine policy.",
                    retry_after_seconds=5,
                )
            profile_id = str(active_profile["id"])
            resource_variant = active_profile.get("resource_variant")
            if not isinstance(resource_variant, str) or not resource_variant.strip():
                resource_variant = None
            profile_source = "runtime_controller_active_profile"
        else:
            profile_id = settings.static_main_profile
            engine_policy = settings.static_main_engine_policy
            resource_variant = settings.static_main_resource_variant
            profile_source = "static_configuration"
            if not profile_id or not isinstance(engine_policy, dict) or not engine_policy:
                raise ServiceError(
                    "MODEL_UNAVAILABLE",
                    "Static Main Model serving configuration is incomplete.",
                )

        return JSONResponse({
            "runtime": "main_llm",
            "public_model": main_endpoint.model,
            "deployment_target": target.target_id,
            "backend": target.runtime_backend,
            "control_mode": target.control_mode,
            "profile": {
                "id": profile_id,
                "resource_variant": resource_variant,
                "source": profile_source,
            },
            "admission": {
                "max_concurrency": main_endpoint.max_concurrency,
                "queue_timeout_seconds": main_endpoint.queue_timeout_seconds,
            },
            "engine": engine_policy,
        })

    _s = _GW[("GET", "/metrics")]

    @router.get(
        "/metrics",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={401: {"description": "Admin Bearer token 필요"}},
    )
    async def metrics_endpoint():
        runtime_controller = getattr(clients, "runtime_controller", None)
        if runtime_controller is not None:
            try:
                # metric projection은 ledger 필드만 읽는다.
                metrics.project_main_model(await runtime_controller.main_model(observed=False))
            except RuntimeControllerUnavailableError:
                metrics.main_model_gate.labels(metrics.service).set(0)
        return metrics.response()

    if metrics.recent_traffic is not None:
        _s = _GW[("GET", "/admin/traffic/recent")]

        @router.get(
            "/admin/traffic/recent",
            dependencies=admin_dependencies,
            tags=[_s.tag],
            summary=_s.summary,
            operation_id=_s.operation_id,
            description=_s.description,
        )
        async def recent_traffic() -> dict[str, Any]:
            return metrics.recent_traffic.snapshot()

    return router
