"""자동 배포도 기존 Main Model 상태·전환·검증 권한을 사용한다."""

from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Mapping

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder

from ..configuration import load_yaml_mapping
from ..docker_scope import require_compose_project
from ..main_model.adaptive import AdaptiveMainModelControl
from ..main_model.adaptive_backend import AdaptiveDockerBackend, AdaptiveResourceReader
from ..main_model.adaptive_catalog import load_adaptive_catalog
from ..main_model.control import MainModelManager
from ..main_model.state import MainModelStateError, MainModelStateStore
from ..main_model.switch_preflight import project_switch_preflight
from ..runtime_controller_config import load_runtime_controller_config
from ..runtime_transition import RuntimeTransitionPlan


def create_adaptive_controller_app(
    *, environment: Mapping[str, str] | None = None, backend=None, resource_reader=None
) -> FastAPI:
    env = dict(os.environ if environment is None else environment)
    config = load_runtime_controller_config(env)
    require_compose_project(config.compose_project)
    catalog, policy, gpu_error = load_adaptive_catalog(config.config_root, env)
    ceiling = policy["gpu_budget_ceiling"]
    if not 0 < ceiling <= 1:
        raise ValueError("GPU budget ceiling must be in (0, 1]")
    observer = load_yaml_mapping(config.config_root / "configs/services.yaml")[
        "services"
    ]["host_resource_observer"]
    reader = resource_reader or AdaptiveResourceReader(
        f"http://{observer['compose_service']}:{observer['container_port']}",
        config.internal_service_token,
    )
    engine = backend or AdaptiveDockerBackend(
        config.docker_socket,
        config.compose_project,
        gateway_url=config.gateway_internal_url,
        internal_token=config.internal_service_token,
        config_root=config.config_root,
        cpu_cache_dir=Path("/models"),
        resource_reader=reader,
        selection_policy=policy,
    )
    store = MainModelStateStore(config.state_path, catalog.default_profile)
    try:
        store.read()
    except MainModelStateError as exc:
        store.quarantine_corrupt_state(str(exc))
    persisted = store.read().get("active_profile")
    if persisted is not None and persisted not in catalog.profiles:
        # GPU Artifact 설정 유실 시 이전 검증을 광고하지 않고 CPU를 다시 검증한다.
        store.update(lambda state: state.update(active_profile=None, gate="closed"))
    manager = MainModelManager(catalog, store, engine)
    control = AdaptiveMainModelControl(manager, policy, reader, gpu_error=gpu_error)

    async def authenticate(authorization: str | None = Header(default=None)):
        if config.internal_service_auth_required and not hmac.compare_digest(
            authorization or "", "Bearer " + config.internal_service_token
        ):
            raise HTTPException(401, detail="invalid internal service token")

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(control.run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await manager.aclose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.main_model_manager = manager
    app.state.adaptive_control = control
    secured = [Depends(authenticate)]

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/main-model", dependencies=secured)
    async def main_model(observed: bool = True):
        value = await manager.observed_snapshot() if observed else manager.snapshot()
        return jsonable_encoder(
            {
                **value,
                "profile_locked": True,
                "runtime_selection": store.read().get(
                    "runtime_selection",
                    {"mode": "automatic", "reason_code": "STARTING_CPU"},
                ),
            }
        )

    @app.get("/main-model/profiles", dependencies=secured)
    async def profiles():
        return {
            "profiles": [
                {
                    **p,
                    "switch_preflight": project_switch_preflight(
                        active=p["active"],
                        policy_error_code="MODEL_PROFILE_LOCKED",
                        participants=None,
                        target_key=str(catalog.runtime["compose_service"]),
                        target_fraction=p["vram_fraction"],
                        ceiling=1.0,
                    ),
                }
                for p in manager.profiles()
            ]
        }

    @app.post("/main-model/switch", dependencies=secured)
    async def manual_switch():
        raise HTTPException(
            409,
            detail={
                "code": "MODEL_PROFILE_LOCKED",
                "message": "Automatic deployment owns CPU/GPU selection; use Main start/stop to suspend or resume serving.",
            },
        )

    @app.get("/main-model/operations", dependencies=secured)
    async def operations():
        return {"items": manager.operations()}

    @app.get("/main-model/operations/{operation_id}", dependencies=secured)
    async def operation(operation_id: str):
        value = manager.operation(operation_id)
        if value is None:
            raise HTTPException(404, detail="operation not found")
        return value

    @app.get("/containers/status", dependencies=secured)
    async def containers_status():
        return {"containers": {}}

    async def budget_snapshot():
        value = manager.snapshot()
        observation = await manager.backend.observe_runtime(catalog)
        status = observation.get("container_state")
        if status not in {
            "running",
            "paused",
            "restarting",
            "created",
            "exited",
            "not_found",
        }:
            raise HTTPException(503, detail="Main runtime state is unobservable")
        active = status in {"running", "paused", "restarting"}
        fraction = float((value.get("active_profile") or {}).get("vram_fraction") or 0)
        used = fraction if active else 0.0
        return {
            "ceiling": ceiling,
            "used": used,
            "free": ceiling - used,
            "participants": [
                {
                    "key": str(catalog.runtime["compose_service"]),
                    "active": active,
                    "vram_fraction": fraction,
                    "criticality": "primary_user_path",
                    "priority": 100,
                    "evictable": False,
                }
            ],
        }

    @app.get("/gpu-budget", dependencies=secured)
    async def gpu_budget():
        return await budget_snapshot()

    async def plan(desired: str, force: bool):
        if desired not in {"active", "stopped"}:
            raise HTTPException(422, detail="invalid desired_state")
        value = manager.snapshot()
        budget = await budget_snapshot()
        active = value["runtime_state"] == "active"
        no_op = (desired == "active") == active
        busy = (value.get("last_operation") or {}).get("status") not in {
            None,
            "completed",
            "failed",
            "rollback_failed",
        }
        before = {k: budget[k] for k in ("ceiling", "used", "free")}
        after = before if no_op else {"ceiling": ceiling, "used": 0.0, "free": ceiling}
        target = str(catalog.runtime["compose_service"])
        result = RuntimeTransitionPlan(
            target_key=target,
            desired_state=desired,
            force=False,
            current_state="active" if active else "stopped",
            no_op=no_op,
            admissible=not busy,
            requires_force=False,
            start=(target,) if not no_op and desired == "active" else (),
            stop=(target,) if not no_op and desired == "stopped" else (),
            prerequisites=(),
            budget_before=before,
            budget_after=after,
            impact=(
                {
                    "key": target,
                    "action": "start" if desired == "active" else "stop",
                    "criticality": "primary_user_path",
                },
            )
            if not no_op
            else (),
            reason="MODEL_SWITCH_IN_PROGRESS" if busy else None,
        )
        return result

    @app.post("/runtime-transitions/{service}/plan", dependencies=secured)
    async def runtime_plan(service: str, payload: dict):
        if service != "main":
            raise HTTPException(404, detail="runtime endpoint not found")
        if (
            set(payload) - {"desired_state", "force"}
            or type(payload.get("force", False)) is not bool
        ):
            raise HTTPException(422, detail="invalid transition request")
        async with control.mutation_lock:
            return (
                await plan(payload.get("desired_state"), payload.get("force", False))
            ).response()

    async def validate_plan(desired: str, digest: str | None):
        fresh = await plan(desired, False)
        if not digest or digest != fresh.digest or not fresh.admissible:
            raise HTTPException(
                409,
                detail={
                    "code": "RUNTIME_PLAN_CHANGED",
                    "message": "Runtime plan changed; review it again.",
                },
            )
        return fresh

    @app.post("/main-model/stop", dependencies=secured)
    async def stop_main(plan_digest: str | None = None):
        async with control.mutation_lock:
            await validate_plan("stopped", plan_digest)
            await manager.stop_main(strict_drain=True)
        return {
            "action": "stop",
            "service": catalog.runtime["compose_service"],
            "runtime_state": "stopped",
        }

    @app.post("/main-model/start", dependencies=secured)
    async def start_main(plan_digest: str | None = None, force: bool = False):
        async with control.mutation_lock:
            reviewed = await validate_plan("active", plan_digest)
            if not reviewed.no_op:
                outcome = manager.request_switch(
                    policy["cpu_profile"], confirm_unverified=True
                )
                operation = await manager.wait_for_operation(outcome.operation_id)
                if operation["status"] != "completed":
                    raise HTTPException(503, detail="CPU startup verification failed")
        return {
            "action": "start",
            "service": catalog.runtime["compose_service"],
            "runtime_state": "active",
            "evicted": [],
        }

    return app
