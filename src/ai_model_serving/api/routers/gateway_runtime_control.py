from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse

from ..endpoint_spec import GATEWAY_ENDPOINTS
from .gateway_main_model_control import build_router as build_main_model_router
from ...errors import ServiceError, error_response, request_id_for
from ..error_responses import runtime_controller_request_error_response, runtime_controller_unavailable_response
from ...api_examples import (
    RUNTIME_BUDGET_EXCEEDED_EXAMPLE,
    RUNTIME_ERROR_404_EXAMPLE,
    RUNTIME_ERROR_503_NO_RUNTIME_CONTROLLER_EXAMPLE,
    RUNTIME_ERROR_503_RUNTIME_CONTROLLER_UNAVAILABLE_EXAMPLE,
    RUNTIME_ERROR_503_TRANSITIONING_EXAMPLE,
    RUNTIME_LIST_MIXED_STATE_EXAMPLE,
    RUNTIME_LIST_RESPONSE_EXAMPLE,
    RUNTIME_TRANSITION_NOOP_EXAMPLE,
    RUNTIME_TRANSITION_TO_ACTIVE_EXAMPLE,
    RUNTIME_TRANSITION_TO_ACTIVE_WITH_PREREQ_EXAMPLE,
    RUNTIME_TRANSITION_TO_STOPPED_EXAMPLE,
    RUNTIME_TRANSITION_TO_STOPPED_WITH_PREREQ_EXAMPLE,
)
from ...security import AdminAuthContext
from ...runtime_transition_history import (
    RuntimeTransitionHistoryCursorError,
    RuntimeTransitionHistoryNotFound,
    RuntimeTransitionHistoryStore,
    RuntimeTransitionHistoryUnavailable,
)
from ...services.runtime_state import RuntimeState, RuntimeStateStore
from ...services.runtime_controller_client import (
    RuntimeControllerClient,
    RuntimeControllerRequestError,
    RuntimeControllerUnavailableError,
)
from ...runtime_transition_contract import (
    parse_runtime_transition_request,
    project_runtime_controller_plan,
)

_GW = {(s.method, s.path): s for s in GATEWAY_ENDPOINTS}

async def _runtime_request_json(request: Request) -> Any:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "Request body must be valid JSON",
            param="body",
        ) from exc


def _container_name(base_url: str) -> str:
    return urlparse(base_url).hostname or ""


def _runtime_transitioning_response() -> JSONResponse:
    # 시작 중에는 일시 오류와 대기 힌트를 함께 반환한다.
    return error_response(
        "MODEL_UNAVAILABLE",
        "runtime is currently starting; wait and retry",
        retry_after_seconds=5,
    )


def _budget_participant(budget: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    for participant in (budget or {}).get("participants", []):
        if participant.get("key") == key:
            return participant
    return None


def _budget_fraction(budget: dict[str, Any] | None, key: str) -> float | None:
    participant = _budget_participant(budget, key)
    return participant.get("vram_fraction") if participant else None


def _main_participant(
    budget: dict[str, Any] | None, secondary_containers: set[str]
) -> dict[str, Any] | None:
    """존재하면 보조 런타임이 아닌 main model 예산 참여자를 반환한다."""
    for participant in (budget or {}).get("participants", []):
        if participant.get("key") not in secondary_containers:
            return participant
    return None


def _validate_service_key(service_key: str, state_store: RuntimeStateStore) -> None:
    if service_key not in state_store.controllable_keys:
        raise HTTPException(404, detail=f"runtime endpoint not found: {service_key}")


def _admin_actor(request: Request) -> dict[str, str]:
    context = getattr(request.state, "admin_auth_context", None)
    if not isinstance(context, AdminAuthContext):
        context = AdminAuthContext(auth_method="local", actor_id="local_operator")
    return {"auth_method": context.auth_method, "actor_id": context.actor_id}


def _history_service_error(exc: RuntimeTransitionHistoryUnavailable, request: Request) -> ServiceError:
    return ServiceError(
        "RUNTIME_HISTORY_UNAVAILABLE",
        "Runtime transition history is temporarily unavailable.",
        request_id=request_id_for(request),
        details={"reason": exc.reason},
    )


def _begin_runtime_operation(
    history: RuntimeTransitionHistoryStore,
    request: Request,
    *,
    service_key: str,
    desired_state: str,
    force: bool,
    plan_digest: str | None,
    before: dict[str, Any],
) -> str:
    try:
        return history.begin(
            service_key=service_key,
            desired_state=desired_state,
            force=force,
            plan_digest=plan_digest,
            actor=_admin_actor(request),
            request_id=request_id_for(request),
            before=before,
        )
    except RuntimeTransitionHistoryUnavailable as exc:
        raise _history_service_error(exc, request) from exc


def _finish_runtime_operation(
    history: RuntimeTransitionHistoryStore,
    request: Request,
    operation_id: str,
    *,
    status: str,
    phase: str,
    apply_result: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return history.finish(
            operation_id,
            status=status,
            phase=phase,
            apply_result=apply_result,
            verification=verification,
            error=error,
        )
    except RuntimeTransitionHistoryUnavailable as exc:
        raise _history_service_error(exc, request) from exc


def _with_operation_header(response: JSONResponse, operation_id: str) -> JSONResponse:
    response.headers["X-Control-Operation-ID"] = operation_id
    return response


def _runtime_history_query(request: Request) -> tuple[int, str | None]:
    params = request.query_params
    allowed = {"limit", "cursor"}
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ServiceError(
            "VALIDATION_ERROR",
            f"unsupported runtime history query parameter(s): {', '.join(unknown)}",
            request_id=request_id_for(request),
            param="query",
        )
    for name in allowed:
        if len(params.getlist(name)) > 1:
            raise ServiceError(
                "VALIDATION_ERROR",
                f"runtime history query parameter must appear at most once: {name}",
                request_id=request_id_for(request),
                param=name,
            )
    raw_limit = params.get("limit")
    if raw_limit is None:
        limit = 50
    elif raw_limit.isascii() and raw_limit.isdecimal() and 1 <= int(raw_limit) <= 200:
        limit = int(raw_limit)
    else:
        raise ServiceError(
            "VALIDATION_ERROR",
            "limit must be an integer between 1 and 200",
            request_id=request_id_for(request),
            param="limit",
        )
    cursor = params.get("cursor")
    if cursor == "":
        raise ServiceError(
            "VALIDATION_ERROR",
            "runtime history cursor is invalid",
            request_id=request_id_for(request),
            param="cursor",
        )
    return limit, cursor


def _secondary_converged(desired_state: str, observed_state: str | None) -> bool:
    if desired_state == "active":
        return observed_state == "running"
    return observed_state in {"exited", "not_found"}


async def _best_effort_secondary_before(
    runtime_controller: RuntimeControllerClient | None,
    container: str,
    desired_state: str,
) -> dict[str, Any]:
    observed_state: str | None = None
    if runtime_controller is not None:
        try:
            observed_state = (await runtime_controller.get_status()).get(container, "not_found")
        except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
            observed_state = None
    return {"desired_state": desired_state, "observed_state": observed_state}


async def _verify_secondary_transition(
    runtime_controller: RuntimeControllerClient,
    *,
    container: str,
    desired_state: str,
    started: list[str],
    stopped: list[str],
    evicted: list[str],
) -> dict[str, Any]:
    statuses = await runtime_controller.get_status()
    observed_state = statuses.get(container, "not_found")
    effects: dict[str, str] = {}
    for name in sorted(set([*started, *stopped, *evicted])):
        effects[name] = statuses.get(name, "not_found")
    effects_converged = all(statuses.get(name, "not_found") == "running" for name in started)
    effects_converged = effects_converged and all(
        statuses.get(name, "not_found") in {"exited", "not_found"}
        for name in [*stopped, *evicted]
    )
    return {
        "converged": _secondary_converged(desired_state, observed_state) and effects_converged,
        "source": "runtime_controller_container_status",
        "desired_state": desired_state,
        "observed_state": observed_state,
        "effects": effects,
    }


async def _best_effort_main_before(runtime_controller: RuntimeControllerClient) -> dict[str, Any]:
    try:
        snapshot = await runtime_controller.main_model()
    except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
        return {"runtime_state": None, "observed_state": None}
    observed = snapshot.get("observed_runtime") or {}
    return {
        "runtime_state": snapshot.get("runtime_state"),
        "observed_state": observed.get("status"),
        "container_state": observed.get("container_state"),
    }


async def _verify_main_transition(
    runtime_controller: RuntimeControllerClient,
    *,
    desired_state: str,
    evicted: list[str],
) -> dict[str, Any]:
    snapshot = await runtime_controller.main_model()
    observed = snapshot.get("observed_runtime") or {}
    observed_status = observed.get("status")
    container_state = observed.get("container_state")
    runtime_state = snapshot.get("runtime_state")
    if desired_state == "active":
        target_converged = (
            runtime_state == "active"
            and observed_status == "ready"
            and container_state == "running"
        )
    else:
        target_converged = (
            runtime_state == "stopped"
            and observed_status == "stopped"
            and container_state != "running"
        )
    effects: dict[str, str] = {}
    effects_converged = True
    if evicted:
        statuses = await runtime_controller.get_status()
        for name in sorted(set(evicted)):
            effects[name] = statuses.get(name, "not_found")
        effects_converged = all(state in {"exited", "not_found"} for state in effects.values())
    return {
        "converged": target_converged and effects_converged,
        "source": "main_model_observed",
        "desired_state": desired_state,
        "runtime_state": runtime_state,
        "observed_state": observed_status,
        "container_state": container_state,
        "effects": effects,
    }


def _verification_failure(
    request: Request,
    operation_id: str,
    verification: dict[str, Any],
) -> ServiceError:
    return ServiceError(
        "RUNTIME_VERIFICATION_FAILED",
        "Runtime transition apply could not be verified against observed state.",
        request_id=request_id_for(request),
        details={"operation_id": operation_id, "verification": verification},
    )


def build_router(
    admin_dependencies: list,
    state_store: RuntimeStateStore,
    runtime_controller: RuntimeControllerClient | None,
    settings: Any,
    history_store: RuntimeTransitionHistoryStore,
) -> APIRouter:
    router = APIRouter()

    container_to_key: dict[str, str] = {
        _container_name(ep.base_url): sk
        for sk, ep in settings.runtime_endpoints.items()
        if sk in state_store.controllable_keys
    }

    def _controllable_runtimes() -> list[dict[str, str]]:
        return [
            {
                "service_key": sk,
                "container": _container_name(ep.base_url),
            }
            for sk, ep in settings.runtime_endpoints.items()
            if sk in state_store.controllable_keys
        ]

    _ADMIN_401 = (
        {401: {"description": "Admin Bearer token 필요"}}
        if settings.security.admin_api_key_required
        else {}
    )

    _s = _GW[("GET", "/admin/runtimes")]

    @router.get(
        "/admin/runtimes",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {"content": {"application/json": {"examples": {
                "all_active": {"summary": "전체 활성", "value": RUNTIME_LIST_RESPONSE_EXAMPLE},
                "mixed_state": {"summary": "중지/시작 중 포함", "value": RUNTIME_LIST_MIXED_STATE_EXAMPLE},
            }}}},
            **_ADMIN_401,
        },
    )
    async def list_runtimes() -> JSONResponse:
        gateway_records = await state_store.all_records()
        container_statuses: dict[str, str] = {}
        budget: dict[str, Any] | None = None
        main_model: dict[str, Any] | None = None
        if runtime_controller is not None:
            try:
                container_statuses = await runtime_controller.get_status()
            except RuntimeControllerUnavailableError:
                container_statuses = {}
            try:
                budget = await runtime_controller.gpu_budget()
            except RuntimeControllerUnavailableError:
                budget = None
            try:
                # 이 목록은 gate·runtime_state·active profile만 쓴다.
                main_model = await runtime_controller.main_model(observed=False)
            except RuntimeControllerUnavailableError:
                main_model = None

        runtimes = []
        for item in _controllable_runtimes():
            sk = item["service_key"]
            container = item["container"]
            record = gateway_records.get(sk)
            state = record.state.value if record is not None else RuntimeState.active.value
            c_status = container_statuses.get(container, "unknown")
            sk_participant = _budget_participant(budget, container)
            runtime = {
                "service_key": sk,
                "container": container,
                "state": state,
                "container_status": c_status,
                "vram_fraction": _budget_fraction(budget, container),
                # 이 런타임이 담당하는 역할; 여기서 축출이 발생하면 무엇이 저하되는지
                "criticality": (sk_participant or {}).get("criticality"),
            }
            if record is not None:
                if record.reason:
                    runtime["state_reason"] = record.reason
                if record.source:
                    runtime["state_source"] = record.source
                if record.updated_at:
                    runtime["state_updated_at"] = record.updated_at
            runtimes.append(runtime)
        # 메인 채팅 모델은 공유 GPU 예산에서 1급 참여자다.
        if main_model is not None:
            active_profile = main_model.get("active_profile") or {}
            main_participant = _main_participant(budget, set(container_to_key))
            runtimes.append({
                "service_key": "main",
                "container": main_participant.get("key") if main_participant else None,
                "state": main_model.get("runtime_state", "active"),
                "container_status": (
                    ("running" if main_participant.get("active") else "stopped")
                    if main_participant
                    else "unknown"
                ),
                "vram_fraction": active_profile.get("vram_fraction"),
                "criticality": (main_participant or {}).get("criticality", "primary_user_path"),
                "gate": main_model.get("gate"),
                "active_profile": active_profile.get("id"),
            })
        body: dict[str, Any] = {
            "runtimes": runtimes,
            "topology": [
                {
                    "service_key": item.service_key,
                    "service_id": item.service_id,
                    "features": list(item.features),
                    "available": item.available,
                    "controllable": item.controllable,
                    "reason_code": item.reason_code,
                    "main_resource_variant": item.main_resource_variant,
                }
                for item in settings.runtime_topology_status
            ],
        }
        if budget is not None:
            body["budget"] = {
                "ceiling": budget.get("ceiling"),
                "used": budget.get("used"),
                "free": budget.get("free"),
            }
        return JSONResponse(body)

    _s = _GW[("PATCH", "/admin/runtimes/{service_key}")]
    runtime_service_keys = [*sorted(state_store.controllable_keys), "main"]
    service_key_path = Path(
        description="GET /admin/runtimes가 반환하는 service_key.",
        examples=[runtime_service_keys[0]],
        json_schema_extra={"enum": runtime_service_keys},
    )

    plan_spec = _GW[("POST", "/admin/runtimes/{service_key}/plans")]

    @router.post(
        "/admin/runtimes/{service_key}/plans",
        dependencies=admin_dependencies,
        tags=[plan_spec.tag],
        summary=plan_spec.summary,
        operation_id=plan_spec.operation_id,
        description=plan_spec.description,
    )
    async def plan_runtime_transition(
        request: Request,
        service_key: str = service_key_path,
    ) -> JSONResponse:
        desired_state, force, _ = parse_runtime_transition_request(
            await _runtime_request_json(request),
            require_plan_digest=False,
        )
        if runtime_controller is None:
            raise ServiceError(
                "MAIN_MODEL_CONTROL_UNAVAILABLE",
                "Runtime Controller is not configured",
                retry_after_seconds=5,
            )
        if service_key == "main":
            runtime_service = "main"
        else:
            _validate_service_key(service_key, state_store)
            ep = settings.runtime_endpoints.get(service_key)
            if ep is None:
                raise ServiceError("NOT_FOUND", f"runtime endpoint not found: {service_key}")
            runtime_service = _container_name(ep.base_url)
        try:
            raw_plan = await runtime_controller.runtime_plan(
                runtime_service,
                desired_state=desired_state,
                force=force,
            )
        except RuntimeControllerRequestError as exc:
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)
        return JSONResponse(
            project_runtime_controller_plan(
                raw_plan,
                service_key=service_key,
                container_to_key=container_to_key,
            )
        )


    history_spec = _GW[("GET", "/admin/runtimes/operations")]

    @router.get(
        "/admin/runtimes/operations",
        dependencies=admin_dependencies,
        tags=[history_spec.tag],
        summary=history_spec.summary,
        operation_id=history_spec.operation_id,
        description=history_spec.description,
    )
    async def list_runtime_transition_operations(request: Request) -> JSONResponse:
        limit, cursor = _runtime_history_query(request)
        try:
            return JSONResponse(history_store.page(limit=limit, cursor=cursor))
        except RuntimeTransitionHistoryCursorError as exc:
            raise ServiceError(
                "VALIDATION_ERROR",
                str(exc),
                request_id=request_id_for(request),
                param="cursor",
            ) from exc
        except RuntimeTransitionHistoryUnavailable as exc:
            raise _history_service_error(exc, request) from exc

    history_detail_spec = _GW[("GET", "/admin/runtimes/operations/{operation_id}")]

    @router.get(
        "/admin/runtimes/operations/{operation_id}",
        dependencies=admin_dependencies,
        tags=[history_detail_spec.tag],
        summary=history_detail_spec.summary,
        operation_id=history_detail_spec.operation_id,
        description=history_detail_spec.description,
        openapi_extra={
            "parameters": [
                {
                    "name": "operation_id",
                    "in": "path",
                    "required": True,
                    "description": "Runtime transition operation id (`rt_<32 hex>`).",
                    "schema": {"type": "string", "pattern": "^rt_[0-9a-f]{32}$"},
                }
            ]
        },
    )
    async def get_runtime_transition_operation(request: Request) -> JSONResponse:
        operation_id = str(request.path_params["operation_id"])
        try:
            return JSONResponse(history_store.get(operation_id))
        except RuntimeTransitionHistoryNotFound as exc:
            raise ServiceError(
                "NOT_FOUND",
                "runtime transition operation not found",
                request_id=request_id_for(request),
            ) from exc
        except RuntimeTransitionHistoryUnavailable as exc:
            raise _history_service_error(exc, request) from exc

    @router.patch(
        "/admin/runtimes/{service_key}",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {"content": {"application/json": {"examples": {
                "to_stopped": {"summary": "보조 중지 (VRAM 회수)", "value": RUNTIME_TRANSITION_TO_STOPPED_EXAMPLE},
                "to_stopped_prereq": {"summary": "보조 중지 — 실제 컨테이너 상태 재확인", "value": RUNTIME_TRANSITION_TO_STOPPED_WITH_PREREQ_EXAMPLE},
                "to_active": {"summary": "보조 시작 (서비스 복구)", "value": RUNTIME_TRANSITION_TO_ACTIVE_EXAMPLE},
                "to_active_prereq": {"summary": "보조 시작 — 선행 컨테이너 포함", "value": RUNTIME_TRANSITION_TO_ACTIVE_WITH_PREREQ_EXAMPLE},
                "noop": {"summary": "이미 목표 상태 (no-op)", "value": RUNTIME_TRANSITION_NOOP_EXAMPLE},
                "main_stopped": {"summary": "메인 정지 (key=main, VRAM 회수)", "value": {"service_key": "main", "state": "stopped", "evicted": []}},
                "main_active": {"summary": "메인 시작 (key=main)", "value": {"service_key": "main", "state": "active", "evicted": []}},
                "main_active_force": {"summary": "메인 시작 + 보조 축출 (force)", "value": {"service_key": "main", "state": "active", "evicted": ["prompt-injection-detector-runtime", "embedding-ko-vllm"]}},
            }}}},
            404: {"content": {"application/json": {"example": RUNTIME_ERROR_404_EXAMPLE}}},
            409: {
                "description": "GPU 예산 초과. 표준 error.code=GPU_BUDGET_EXCEEDED와 error.details.plan.stop을 반환한다. force=true로 자동 축출.",
                "content": {"application/json": {"examples": {
                    "budget_exceeded": {"summary": "GPU 예산 초과 + 정지 계획", "value": RUNTIME_BUDGET_EXCEEDED_EXAMPLE},
                }}},
            },
            503: {"content": {"application/json": {"examples": {
                "no_runtime_controller": {"summary": "Runtime Controller 미설정", "value": RUNTIME_ERROR_503_NO_RUNTIME_CONTROLLER_EXAMPLE},
                "runtime_controller_unavailable": {"summary": "Runtime Controller 연결 실패", "value": RUNTIME_ERROR_503_RUNTIME_CONTROLLER_UNAVAILABLE_EXAMPLE},
                "in_progress": {"summary": "전환 중 (재시도 가능)", "value": RUNTIME_ERROR_503_TRANSITIONING_EXAMPLE},
            }}}},
            **_ADMIN_401,
        },
    )
    async def transition_runtime(
        request: Request,
        service_key: str = service_key_path,
    ) -> JSONResponse:
        desired_state, force, plan_digest = parse_runtime_transition_request(
            await _runtime_request_json(request),
            require_plan_digest=True,
        )

        if service_key == "main":
            if runtime_controller is None:
                raise HTTPException(503, detail="Runtime Controller is not configured (RUNTIME_CONTROLLER_URL missing)")
            before = await _best_effort_main_before(runtime_controller)
            operation_id = _begin_runtime_operation(
                history_store,
                request,
                service_key=service_key,
                desired_state=desired_state,
                force=force,
                plan_digest=plan_digest,
                before=before,
            )
            try:
                if desired_state == "active":
                    result = await runtime_controller.main_start(
                        force=force,
                        plan_digest=plan_digest,
                    )
                    for evicted_container in result.get("evicted", []):
                        evicted_key = container_to_key.get(evicted_container)
                        if evicted_key:
                            await state_store.set(
                                evicted_key,
                                RuntimeState.stopped,
                                reason="evicted_by_main_start",
                                source="runtime_control",
                            )
                else:
                    result = await runtime_controller.main_stop(plan_digest=plan_digest)
            except RuntimeControllerRequestError as exc:
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="rejected",
                    phase="apply",
                    apply_result=None,
                    verification=None,
                    error={"code": "runtime_controller_request_rejected", "status_code": exc.status_code},
                )
                return _with_operation_header(runtime_controller_request_error_response(exc), operation_id)
            except RuntimeControllerUnavailableError as exc:
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="apply_failed",
                    phase="apply",
                    apply_result=None,
                    verification=None,
                    error={"code": "runtime_controller_unavailable"},
                )
                return _with_operation_header(runtime_controller_unavailable_response(exc), operation_id)

            apply_result = {
                "state": result.get("runtime_state", desired_state),
                "evicted": list(result.get("evicted", [])),
            }
            try:
                verification = await _verify_main_transition(
                    runtime_controller,
                    desired_state=desired_state,
                    evicted=apply_result["evicted"],
                )
            except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
                verification = {
                    "converged": False,
                    "source": "main_model_observed",
                    "desired_state": desired_state,
                    "reason": "observation_unavailable",
                }
            if not verification["converged"]:
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="verification_failed",
                    phase="verify",
                    apply_result=apply_result,
                    verification=verification,
                    error={"code": "verification_failed"},
                )
                raise _verification_failure(request, operation_id, verification)
            _finish_runtime_operation(
                history_store,
                request,
                operation_id,
                status="verified",
                phase="completed",
                apply_result=apply_result,
                verification=verification,
            )
            return JSONResponse({
                "service_key": "main",
                "state": apply_result["state"],
                "evicted": apply_result["evicted"],
                "operation_id": operation_id,
                "operation_status": "verified",
                "verification": verification,
            })

        _validate_service_key(service_key, state_store)
        current_state = await state_store.get(service_key)
        ep = settings.runtime_endpoints.get(service_key)
        if ep is None:
            raise HTTPException(404, detail=f"runtime endpoint not found: {service_key}")
        container = _container_name(ep.base_url)
        actual: str | None = None

        if desired_state == "active":
            if current_state == RuntimeState.active and runtime_controller is not None:
                try:
                    actual = (await runtime_controller.get_status()).get(container, "not_found")
                except RuntimeControllerRequestError as exc:
                    return runtime_controller_request_error_response(exc)
                except RuntimeControllerUnavailableError as exc:
                    return runtime_controller_unavailable_response(exc)
            if current_state == RuntimeState.starting:
                return _runtime_transitioning_response()
            if runtime_controller is None:
                raise HTTPException(503, detail="Runtime Controller is not configured (RUNTIME_CONTROLLER_URL missing)")
            before = {
                "desired_state": current_state.value,
                "observed_state": actual,
            }
            if actual is None:
                observed = await _best_effort_secondary_before(runtime_controller, container, current_state.value)
                before["observed_state"] = observed["observed_state"]
            operation_id = _begin_runtime_operation(
                history_store,
                request,
                service_key=service_key,
                desired_state=desired_state,
                force=force,
                plan_digest=plan_digest,
                before=before,
            )
            await state_store.set(
                service_key,
                RuntimeState.starting,
                reason="operator_start_requested",
                source="runtime_control",
            )
            try:
                result = await runtime_controller.start(
                    container,
                    force=force,
                    plan_digest=plan_digest,
                )
            except RuntimeControllerRequestError as exc:
                await state_store.set(
                    service_key,
                    RuntimeState.stopped,
                    reason="start_rejected",
                    source="runtime_control",
                )
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="rejected",
                    phase="apply",
                    apply_result=None,
                    verification=None,
                    error={"code": "runtime_controller_request_rejected", "status_code": exc.status_code},
                )
                return _with_operation_header(runtime_controller_request_error_response(exc), operation_id)
            except RuntimeControllerUnavailableError as exc:
                await state_store.set(
                    service_key,
                    RuntimeState.stopped,
                    reason="start_runtime_controller_unavailable",
                    source="runtime_control",
                )
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="apply_failed",
                    phase="apply",
                    apply_result=None,
                    verification=None,
                    error={"code": "runtime_controller_unavailable"},
                )
                return _with_operation_header(runtime_controller_unavailable_response(exc), operation_id)
            started_containers = list(result.get("started", []))
            evicted_containers = list(result.get("evicted", []))
            for evicted_container in evicted_containers:
                evicted_key = container_to_key.get(evicted_container)
                if evicted_key:
                    await state_store.set(
                        evicted_key,
                        RuntimeState.stopped,
                        reason="evicted_by_runtime_start",
                        source="runtime_control",
                    )
            for started_container in started_containers:
                started_key = container_to_key.get(started_container)
                if started_key:
                    await state_store.set(
                        started_key,
                        RuntimeState.active,
                        reason="started_by_runtime_control",
                        source="runtime_control",
                    )
            await state_store.set(
                service_key,
                RuntimeState.active,
                reason="started_by_runtime_control",
                source="runtime_control",
            )
            apply_result = {
                "containers_started": started_containers,
                "evicted": evicted_containers,
            }
            try:
                verification = await _verify_secondary_transition(
                    runtime_controller,
                    container=container,
                    desired_state=desired_state,
                    started=started_containers,
                    stopped=[],
                    evicted=evicted_containers,
                )
            except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
                verification = {
                    "converged": False,
                    "source": "runtime_controller_container_status",
                    "desired_state": desired_state,
                    "observed_state": None,
                    "reason": "observation_unavailable",
                }
            if not verification["converged"]:
                _finish_runtime_operation(
                    history_store,
                    request,
                    operation_id,
                    status="verification_failed",
                    phase="verify",
                    apply_result=apply_result,
                    verification=verification,
                    error={"code": "verification_failed"},
                )
                raise _verification_failure(request, operation_id, verification)
            _finish_runtime_operation(
                history_store,
                request,
                operation_id,
                status="verified",
                phase="completed",
                apply_result=apply_result,
                verification=verification,
            )
            return JSONResponse({
                "service_key": service_key,
                "state": "active",
                **apply_result,
                "operation_id": operation_id,
                "operation_status": "verified",
                "verification": verification,
            })

        if current_state == RuntimeState.stopped and runtime_controller is not None:
            try:
                actual = (await runtime_controller.get_status()).get(container, "not_found")
            except RuntimeControllerRequestError as exc:
                return runtime_controller_request_error_response(exc)
            except RuntimeControllerUnavailableError as exc:
                return runtime_controller_unavailable_response(exc)
        if current_state == RuntimeState.starting:
            return _runtime_transitioning_response()
        if runtime_controller is None:
            raise HTTPException(503, detail="Runtime Controller is not configured (RUNTIME_CONTROLLER_URL missing)")
        before = {"desired_state": current_state.value, "observed_state": actual}
        if actual is None:
            observed = await _best_effort_secondary_before(runtime_controller, container, current_state.value)
            before["observed_state"] = observed["observed_state"]
        operation_id = _begin_runtime_operation(
            history_store,
            request,
            service_key=service_key,
            desired_state=desired_state,
            force=force,
            plan_digest=plan_digest,
            before=before,
        )
        await state_store.set(
            service_key,
            RuntimeState.stopped,
            reason="operator_stop_requested",
            source="runtime_control",
        )
        try:
            stopped_containers = await runtime_controller.stop(
                container,
                plan_digest=plan_digest,
            )
        except RuntimeControllerRequestError as exc:
            _finish_runtime_operation(
                history_store,
                request,
                operation_id,
                status="rejected",
                phase="apply",
                apply_result=None,
                verification=None,
                error={"code": "runtime_controller_request_rejected", "status_code": exc.status_code},
            )
            return _with_operation_header(runtime_controller_request_error_response(exc), operation_id)
        except RuntimeControllerUnavailableError as exc:
            await state_store.set(
                service_key,
                RuntimeState.active,
                reason="stop_runtime_controller_unavailable",
                source="runtime_control",
            )
            _finish_runtime_operation(
                history_store,
                request,
                operation_id,
                status="apply_failed",
                phase="apply",
                apply_result=None,
                verification=None,
                error={"code": "runtime_controller_unavailable"},
            )
            return _with_operation_header(runtime_controller_unavailable_response(exc), operation_id)
        stopped = list(stopped_containers)
        apply_result = {"containers_stopped": stopped}
        try:
            verification = await _verify_secondary_transition(
                runtime_controller,
                container=container,
                desired_state=desired_state,
                started=[],
                stopped=stopped,
                evicted=[],
            )
        except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
            verification = {
                "converged": False,
                "source": "runtime_controller_container_status",
                "desired_state": desired_state,
                "observed_state": None,
                "reason": "observation_unavailable",
            }
        if not verification["converged"]:
            _finish_runtime_operation(
                history_store,
                request,
                operation_id,
                status="verification_failed",
                phase="verify",
                apply_result=apply_result,
                verification=verification,
                error={"code": "verification_failed"},
            )
            raise _verification_failure(request, operation_id, verification)
        _finish_runtime_operation(
            history_store,
            request,
            operation_id,
            status="verified",
            phase="completed",
            apply_result=apply_result,
            verification=verification,
        )
        return JSONResponse({
            "service_key": service_key,
            "state": "stopped",
            **apply_result,
            "operation_id": operation_id,
            "operation_status": "verified",
            "verification": verification,
        })

    router.include_router(
        build_main_model_router(admin_dependencies, runtime_controller, settings)
    )

    return router
