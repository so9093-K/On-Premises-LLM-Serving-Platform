from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..endpoint_spec import GATEWAY_ENDPOINTS
from ..error_responses import (
    runtime_controller_request_error_response,
    runtime_controller_unavailable_response,
)
from ...api_examples import (
    MAIN_MODEL,
    PLACEHOLDER_RUNTIME_IMAGE,
    alternate_main_model_profile_id,
    default_main_model_profile_id,
    main_model_profile_example,
)
from ...errors import ServiceError
from ...services.runtime_controller_client import (
    RuntimeControllerClient,
    RuntimeControllerRequestError,
    RuntimeControllerUnavailableError,
)

# 예시의 모델 신원은 configs/main_model_profiles.yaml에서 그대로 온다. 손으로
# 적어두면 default_profile이나 체크포인트 pin이 바뀔 때 /docs와 OpenAPI 스냅샷만
# 옛 모델을 계속 광고한다.
_DEFAULT_PROFILE_ID = default_main_model_profile_id()
_ALTERNATE_PROFILE_ID = alternate_main_model_profile_id()

_GW = {(s.method, s.path): s for s in GATEWAY_ENDPOINTS}
_OPERATION_ID_EXAMPLE = "41cf50bb-60b2-4dbc-b38a-7dd07da91d97"
_OPERATION_ID_PARAMETER = {
    "name": "operation_id",
    "in": "path",
    "required": True,
    "description": "switch 202 응답의 `operation_id` (UUID).",
    "schema": {"type": "string", "format": "uuid"},
    "example": _OPERATION_ID_EXAMPLE,
}
_OPERATION_RESPONSE_EXAMPLES = {
    "in_progress": {
        "summary": "진행 중 (validating)",
        "value": {
            "id": _OPERATION_ID_EXAMPLE,
            "requested_profile": _DEFAULT_PROFILE_ID,
            "previous_profile": _ALTERNATE_PROFILE_ID,
            "client_request_id": "ops-20260622-12b",
            "status": "validating",
            "stage": "validating",
            "error": None,
            "rollback_error": None,
            "recovered_after_restart": False,
            "created_at": 1782086105.78,
            "updated_at": 1782086230.12,
        },
    },
    "completed": {
        "summary": "완료",
        "value": {
            "id": _OPERATION_ID_EXAMPLE,
            "requested_profile": _DEFAULT_PROFILE_ID,
            "previous_profile": _ALTERNATE_PROFILE_ID,
            "client_request_id": "ops-20260622-12b",
            "status": "completed",
            "stage": "completed",
            "error": None,
            "rollback_error": None,
            "recovered_after_restart": False,
            "created_at": 1782086105.78,
            "updated_at": 1782086258.20,
        },
    },
    "failed": {
        "summary": "실패 후 이전 프로필로 rollback",
        "value": {
            "id": _OPERATION_ID_EXAMPLE,
            "requested_profile": _DEFAULT_PROFILE_ID,
            "previous_profile": _ALTERNATE_PROFILE_ID,
            "client_request_id": "ops-20260622-12b",
            "status": "failed",
            "stage": "validating",
            "error": "runtime validation failed: /v1/models did not report local-main",
            "rollback_error": None,
            "recovered_after_restart": False,
            "created_at": 1782086105.78,
            "updated_at": 1782086240.55,
        },
    },
}
_ACCEPTED_SCHEMA = {
    "type": "object",
    "required": ["operation_id", "status", "reused"],
    "properties": {
        "operation_id": {"type": "string", "format": "uuid"},
        "status": {
            "type": "string",
            "description": "operation 현재 stage/status. 새 전환은 pending으로 시작하고, 동일 request_id 재생 시 기존 작업의 status(예: completed)를 그대로 반환한다.",
        },
        "reused": {
            "type": "boolean",
            "description": "true면 동일 request_id의 기존 작업을 반환한 것이며 새 전환은 시작되지 않았다.",
        },
        "message": {
            "type": "string",
            "description": "운영자용 설명 — 재생 여부와 진행 상황 조회 위치를 안내한다.",
        },
    },
}
_MAIN_MODEL_STATUS_EXAMPLE = {
    "public_model": MAIN_MODEL,
    "active_profile": main_model_profile_example(_DEFAULT_PROFILE_ID),
    "last_known_good_profile": _DEFAULT_PROFILE_ID,
    "previous_known_good_profile": None,
    "gate": "open",
    "runtime_state": "active",
    "profile_locked": False,
    "boot_profile": _DEFAULT_PROFILE_ID,
    "last_operation": None,
    "observed_runtime": {
        "status": "ready",
        "container_state": "running",
        "health": "healthy",
        "profile_id": _DEFAULT_PROFILE_ID,
        "image_ref": PLACEHOLDER_RUNTIME_IMAGE,
        "image_id": "sha256:" + "1" * 64,
        "image_digest": PLACEHOLDER_RUNTIME_IMAGE.split("@", 1)[1],
        "runtime_engine": {"name": "vllm", "version": "0.25.1"},
        "error": None,
        "observed_at": 1782086258.2,
    },
}


def _switch_examples(
    profile_summaries: tuple[tuple[str, str, str], ...],
) -> dict[str, dict[str, Any]]:
    """profile 전환 예시를 catalog에서 그대로 만든다.

    손으로 적으면 catalog에 profile을 추가할 때 조용히 빠진다(E4B가 실제로 그랬다).
    `unverified` profile은 `confirm_unverified`가 있어야 전환되므로 예시에도 함께
    싣는다 -- 목록에서 감추는 것보다 필요한 요청 모양을 보여주는 편이 낫다.
    """
    examples: dict[str, dict[str, Any]] = {}
    for profile_id, display_name, status in profile_summaries:
        value: dict[str, Any] = {"profile": profile_id}
        if status != "verified":
            value["confirm_unverified"] = True
        examples[profile_id.replace("-", "_").replace(".", "_")] = {
            "summary": f"{display_name} ({status or 'unknown'})",
            "value": value,
        }
    return examples


def build_router(
    admin_dependencies: list,
    runtime_controller: RuntimeControllerClient | None,
    settings: Any,
) -> APIRouter:
    router = APIRouter()

    async def require_runtime_controller() -> RuntimeControllerClient:
        if runtime_controller is None:
            raise ServiceError(
                "MAIN_MODEL_CONTROL_UNAVAILABLE",
                "Runtime Controller is not configured",
                retry_after_seconds=5,
            )
        return runtime_controller

    _s = _GW[("GET", "/admin/main-model")]

    @router.get(
        "/admin/main-model",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {
                "description": "마지막 검증 control-plane 상태와 Docker에서 방금 관측한 main-model 상태",
                "content": {
                    "application/json": {"examples": {
                        "active": {
                            "summary": "서비스 가능 (gate open, Docker health healthy)",
                            "value": _MAIN_MODEL_STATUS_EXAMPLE,
                        },
                        "stopped": {
                            "summary": "정지됨 (VRAM 회수, gate closed)",
                            "value": {**_MAIN_MODEL_STATUS_EXAMPLE, "gate": "closed", "runtime_state": "stopped", "observed_runtime": {"status": "stopped", "container_state": "exited", "health": None, "profile_id": _DEFAULT_PROFILE_ID, "image_ref": PLACEHOLDER_RUNTIME_IMAGE, "image_id": "sha256:" + "1" * 64, "image_digest": PLACEHOLDER_RUNTIME_IMAGE.split("@", 1)[1], "runtime_engine": {"name": "vllm", "version": "0.25.1"}, "error": None, "observed_at": 1782086258.2}},
                        },
                        "switch_in_progress": {
                            "summary": "전환 중 (gate closed, 작업 진행)",
                            "value": {
                                **_MAIN_MODEL_STATUS_EXAMPLE,
                                "gate": "closed",
                                "last_operation": {
                                    "id": "8f3c2b10-0000-4000-8000-000000000001",
                                    "requested_profile": _DEFAULT_PROFILE_ID,
                                    "previous_profile": _ALTERNATE_PROFILE_ID,
                                    "status": "validating",
                                    "stage": "validating",
                                },
                                "observed_runtime": {"status": "starting", "container_state": "running", "health": "starting", "profile_id": _DEFAULT_PROFILE_ID, "image_ref": PLACEHOLDER_RUNTIME_IMAGE, "image_id": "sha256:" + "1" * 64, "image_digest": PLACEHOLDER_RUNTIME_IMAGE.split("@", 1)[1], "runtime_engine": {"name": "vllm", "version": "0.25.1"}, "error": None, "observed_at": 1782086258.2},
                            },
                        },
                    }}
                },
            },
            503: {"description": "Runtime Controller 연결 또는 상태 파일 오류"},
        },
    )
    async def get_main_model() -> JSONResponse:
        client = await require_runtime_controller()
        try:
            return JSONResponse(await client.main_model())
        except RuntimeControllerRequestError as exc:
            # 4xx는 요청이 잘못된 것이다. control plane 장애(503, retryable)로
            # 보고하면 성공할 수 없는 요청을 계속 재시도하게 된다.
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)

    _s = _GW[("GET", "/admin/main-model/profiles")]

    @router.get(
        "/admin/main-model/profiles",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        operation_id=_s.operation_id,
        description=_s.description,
        responses={
            200: {
                "description": "허용된 프로필 목록",
                "content": {
                    "application/json": {
                        "example": {
                            "profiles": [
                                main_model_profile_example(_DEFAULT_PROFILE_ID, active=True),
                                main_model_profile_example(_ALTERNATE_PROFILE_ID, active=False),
                            ]
                        }
                    }
                },
            },
            503: {"description": "Runtime Controller 연결 실패"},
        },
    )
    async def list_main_model_profiles() -> JSONResponse:
        client = await require_runtime_controller()
        try:
            return JSONResponse({"profiles": await client.main_model_profiles()})
        except RuntimeControllerRequestError as exc:
            # 4xx는 요청이 잘못된 것이다. control plane 장애(503, retryable)로
            # 보고하면 성공할 수 없는 요청을 계속 재시도하게 된다.
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)

    _s = _GW[("POST", "/admin/main-model/switch")]

    @router.post(
        "/admin/main-model/switch",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        description=_s.description,
        operation_id=_s.operation_id,
        status_code=202,
        responses={
            202: {
                "description": "전환 작업 접수",
                "content": {"application/json": {"schema": _ACCEPTED_SCHEMA}},
            },
            409: {"description": "전환 중, locked, confirmation 필요 또는 request_id 충돌"},
            422: {"description": "잘못된 profile 또는 request"},
            503: {"description": "Runtime Controller 연결 실패"},
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["profile"],
                            "properties": {
                                "profile": {
                                    "type": "string",
                                    "description": "configs/main_model_profiles.yaml의 profile ID",
                                },
                                "confirm_unverified": {"type": "boolean", "default": False},
                                "request_id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 128,
                                },
                            },
                        },
                        "examples": _switch_examples(settings.main_model_profile_summaries),
                    }
                },
            }
        },
    )
    async def switch_main_model(request: Request) -> JSONResponse:
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("profile"), str):
            raise ServiceError("VALIDATION_ERROR", "profile is required", param="profile")
        unknown = set(payload) - {"profile", "confirm_unverified", "request_id"}
        if unknown:
            raise ServiceError(
                "VALIDATION_ERROR",
                f"unsupported fields: {sorted(unknown)}",
                param=sorted(unknown)[0],
            )
        client = await require_runtime_controller()
        try:
            result = await client.switch_main_model(
                payload["profile"],
                confirm_unverified=payload.get("confirm_unverified") is True,
                request_id=payload.get("request_id"),
            )
            return JSONResponse(result, status_code=202)
        except RuntimeControllerRequestError as exc:
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)

    _s = _GW[("GET", "/admin/main-model/operations")]

    @router.get(
        "/admin/main-model/operations",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        description=_s.description,
        operation_id=_s.operation_id,
        responses={
            200: {
                "description": "최근 보존된 Main Model profile switch operation (최신 순)",
                "content": {
                    "application/json": {
                        "example": {
                            "items": [_OPERATION_RESPONSE_EXAMPLES["completed"]["value"]]
                        }
                    }
                },
            },
            503: {"description": "Runtime Controller 연결 실패"},
        },
    )
    async def list_main_model_operations() -> JSONResponse:
        client = await require_runtime_controller()
        try:
            return JSONResponse(await client.main_model_operations())
        except RuntimeControllerRequestError as exc:
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)

    _s = _GW[("GET", "/admin/main-model/operations/{operation_id}")]

    @router.get(
        "/admin/main-model/operations/{operation_id}",
        dependencies=admin_dependencies,
        tags=[_s.tag],
        summary=_s.summary,
        description=_s.description,
        operation_id=_s.operation_id,
        responses={
            200: {
                "description": "전환 작업 상태",
                "content": {
                    "application/json": {
                        "examples": _OPERATION_RESPONSE_EXAMPLES,
                    }
                },
            },
            404: {"description": "operation 없음 (id 오타이거나 만료/미존재)"},
            503: {"description": "Runtime Controller 연결 실패"},
        },
        openapi_extra={"parameters": [_OPERATION_ID_PARAMETER]},
    )
    async def get_main_model_operation(request: Request) -> JSONResponse:
        operation_id = str(request.path_params["operation_id"])
        client = await require_runtime_controller()
        try:
            return JSONResponse(await client.main_model_operation(operation_id))
        except RuntimeControllerRequestError as exc:
            # 404(없는 operation)는 여기서 NOT_FOUND / retryable=false로 나간다.
            return runtime_controller_request_error_response(exc)
        except RuntimeControllerUnavailableError as exc:
            return runtime_controller_unavailable_response(exc)

    # 메인 정지/시작은 별도 엔드포인트가 아니다: 메인 모델도 예산 참여자이며
    # 통일된 fleet verb인 PATCH /admin/runtimes/main {desired_state}로
    # 정지/시작된다. main 전용 프로필 변경(switch)만 /admin/main-model
    # 아래에 있다.

    return router
