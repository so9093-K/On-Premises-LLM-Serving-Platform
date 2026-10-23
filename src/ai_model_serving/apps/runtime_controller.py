from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..main_model.execution_policy import (
    CPU_FIRST_POLICIES, EXECUTION_POLICIES, RECOVERING_POLICIES, resolve_execution_policy,
)
from ..main_model.adaptive import AdaptiveMainModelControl
from ..main_model.adaptive_backend import ManagedDockerBackend, AdaptiveResourceReader
from ..main_model.adaptive_catalog import load_adaptive_catalog
from ..main_model.managed_catalog import load_managed_catalog
from ..configuration import load_yaml_mapping
from ..runtime_controller_config import RuntimeControllerConfig, load_runtime_controller_config
from ..gpu_budget import Participant, budget_snapshot, plan_activation
from ..service_logging import service_logger
from ..main_model.catalog import (
    resource_variant_from_mapping,
)
from ..main_model.control import MainModelManager, MainModelSwitchError, MainModelRuntimeBackend
from ..main_model.runtime_limits import RuntimeLimitError, build_runtime_limit_profile
from ..main_model.switch_preflight import project_switch_preflight
from ..main_model.state import MainModelStateError, MainModelStateStore
from ..log_target_manifest import build_targets, write_manifest
from ..docker_scope import (
    compose_container_filter,
    require_compose_project,
    scoped_container_id,
)
from ..runtime_topology import load_runtime_topology
from ..runtime_transition import plan_runtime_transition
from ..runtime_transition_contract import is_valid_plan_digest
from ..runtime_executor import DockerRuntimeExecutor, RuntimeExecutor, gpu_reservation_active

_logger = service_logger("runtime_controller")

# --------------------------------------------------------------------- config

def create_runtime_controller_app(
    config: RuntimeControllerConfig | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    executor: RuntimeExecutor | None = None,
    main_model_backend: MainModelRuntimeBackend | None = None,
    resource_reader=None,
) -> FastAPI:
    """설정·Lock·Task·실행 어댑터를 인스턴스별로 조립한다.

    테스트는 독립 App을 생성하므로 모듈 reload가 필요하지 않다.
    다중 App 생성은 동일 GPU에 대한 다중 프로세스 쓰기 권한을 의미하지 않는다.
    """
    environment = dict(os.environ if environment is None else environment)
    context = SimpleNamespace()

    context._CONFIG = config or load_runtime_controller_config(environment)
    context.DOCKER_SOCKET = context._CONFIG.docker_socket
    context.COMPOSE_PROJECT = context._CONFIG.compose_project
    context.APP_CONFIG_ROOT = context._CONFIG.config_root
    context.MAIN_MODEL_STATE_PATH = context._CONFIG.state_path
    context.MAIN_MODEL_BOOT_PROFILE = context._CONFIG.boot_profile
    context.MAIN_MODEL_PROFILE_LOCKED = context._CONFIG.profile_locked
    context.MAIN_MODEL_SWITCH_IDEMPOTENCY_TTL_SECONDS = context._CONFIG.idempotency_ttl_seconds
    context.RUNTIME_CONTROLLER_TOKEN = context._CONFIG.internal_service_token
    context.LOG_TARGET_MANIFEST_PATH = context._CONFIG.log_target_manifest_path
    context.LOG_TARGET_REFRESH_SECONDS = context._CONFIG.log_target_refresh_seconds

    context._TOPOLOGY = load_runtime_topology(
        context.APP_CONFIG_ROOT,
        main_resource_variant=resource_variant_from_mapping(environment),
        environment=environment,
    )
    context.CONTROLLABLE: frozenset[str] = context._TOPOLOGY.controllable_services
    # health URL은 topology가 소유한다. 경로 파라미터로 들어온 service 문자열로
    # URL을 조립하지 않기 위해서다 -- allowlist(context.CONTROLLABLE)가 이미 값을 막지만,
    # 조립 자체를 없애면 "무엇을 부르는가"가 설정 한 곳에서만 결정된다.
    context._HEALTH_URL: dict[str, str] = dict(context._TOPOLOGY.health_url_by_service)
    context._START_PREREQUISITES: dict[str, list[str]] = dict(context._TOPOLOGY.start_prerequisites_by_service)
    context._VRAM_FRACTION: dict[str, float] = dict(context._TOPOLOGY.vram_fraction_by_service)
    # 표준 GPU VRAM 예산은 configs/gpu_budgets.yaml에 있다(단일 소스이며
    # 정적·런타임 검증에서도 함께 사용된다). admission ceiling은
    # 그 정책의 "avoid_above" 비율 값이다.
    #
    # 의도적으로 strict하게 읽는다(누락/오타 시 기본값으로 조용히 폴백하지 않고
    # 바로 실패): 여기서 default(0.95)로 폴백하면 실제 정책값(0.93)보다 느슨한
    # ceiling으로 admission이 동작하게 되어, GPU 예산 초과를 막아야 할 안전장치가
    # 설정 오타 하나로 fail-open이 된다.
    _gpu_budgets_path = context.APP_CONFIG_ROOT / "configs/gpu_budgets.yaml"
    _gpu_budgets_cfg = load_yaml_mapping(_gpu_budgets_path)
    context._GPU_BUDGET_CEILING = float(_gpu_budgets_cfg["gpu"]["total_gpu_memory_utilization"]["avoid_above"])

    context._CRITICALITY: dict[str, str] = dict(context._TOPOLOGY.criticality_by_service)
    # criticality별 eviction 정책: priority가 높을수록 더 나중에 evict된다. 주 사용자
    # 경로(primary user path, main)는 절대 자동 evict되지 않으며, risk/safety 경로는
    # retrieval support보다 더 오래 유지된다. 알 수 없는 role은 기본 evictable tier에 속한다.
    context._CRITICALITY_PRIORITY: dict[str, tuple[int, bool]] = {
        "primary_user_path": (100, False),
        "risk_signal_path": (60, True),
        "retrieval_support_path": (50, True),
    }
    context._MAIN_PRIORITY = 100


    def _eviction_policy(criticality: str) -> tuple[int, bool]:
        return context._CRITICALITY_PRIORITY.get(criticality, (50, True))

    # ------------------------------------------------------------------ docker api

    def _docker_client() -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(uds=context.DOCKER_SOCKET)
        return httpx.AsyncClient(transport=transport, base_url="http://docker")


    def _compose_project_filter() -> str:
        return compose_container_filter(context.COMPOSE_PROJECT)


    async def _refresh_log_targets() -> int:
        """현재 Compose 프로젝트의 실행 컨테이너를 Alloy target manifest로 투영한다.

        이 작업은 monitoring 보조 경로다. Docker API/파일 I/O 실패가 Runtime Controller health나
        model control plane을 실패시키지 않도록 호출자가 예외를 기록하고 재시도한다.
        """
        if not context.COMPOSE_PROJECT:
            raise RuntimeError("COMPOSE_PROJECT is required for log target projection")
        async with _docker_client() as dc:
            listed = await dc.get(
                "/containers/json",
                params={"filters": _compose_project_filter()},
                timeout=5.0,
            )
            listed.raise_for_status()
            containers = listed.json()
            inspected: list[Mapping[str, Any]] = []
            for container in containers:
                if not isinstance(container, Mapping):
                    raise RuntimeError("Docker container listing contains a non-object row")
                container_id = scoped_container_id(
                    container,
                    project=context.COMPOSE_PROJECT,
                )
                response = await dc.get(f"/containers/{container_id}/json", timeout=5.0)
                response.raise_for_status()
                inspected.append(response.json())
        targets = build_targets(inspected)
        write_manifest(context.LOG_TARGET_MANIFEST_PATH, targets)
        return len(targets)


    def _executor() -> RuntimeExecutor:
        if executor is not None:
            return executor
        # 로컬 테스트와 애플리케이션 단독 실행에서도 Controller를 Import할 수 있게 둔다.
        # 실제 Managed Executor 호출 시에는 Compose 프로젝트 소속을 검증한다.
        return DockerRuntimeExecutor(
            docker_socket=context.DOCKER_SOCKET,
            compose_project=context.COMPOSE_PROJECT,
            allowed_services=context.CONTROLLABLE,
            status_only_services=frozenset({context._MAIN_SERVICE}),
        )


    context._executor = _executor

    async def _wait_healthy(service: str, url: str, timeout: float = 120.0) -> bool:
        """``url``이 200을 돌려줄 때까지 기다린다. ``service``는 로그 식별용이다."""
        deadline = asyncio.get_running_loop().time() + timeout
        last_detail = "no response"
        async with httpx.AsyncClient(timeout=2.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
                    last_detail = f"HTTP {resp.status_code}"
                except httpx.HTTPError as exc:
                    last_detail = type(exc).__name__
                await asyncio.sleep(3.0)
        _logger.warning("runtime health check timed out: service=%s url=%s last_result=%s", service, url, last_detail)
        return False


    context._wait_healthy = _wait_healthy

    context._state_store = MainModelStateStore(context.MAIN_MODEL_STATE_PATH, "cpu-gguf-text")
    try:
        context._state_store.read()
    except MainModelStateError as exc:
        context._state_store.quarantine_corrupt_state(str(exc))
    seed = resolve_execution_policy(context._state_store.read(), {**environment, "MAIN_MODEL_BOOT_PROFILE": context.MAIN_MODEL_BOOT_PROFILE})
    context._catalog = load_managed_catalog(context.APP_CONFIG_ROOT, environment, cpu_available=seed in CPU_FIRST_POLICIES or context.MAIN_MODEL_BOOT_PROFILE == "cpu-gguf-text")
    _, selection_policy, gpu_policies = load_adaptive_catalog(context.APP_CONFIG_ROOT, environment)
    if context.MAIN_MODEL_BOOT_PROFILE is not None and context.MAIN_MODEL_BOOT_PROFILE not in context._catalog.profiles and seed in CPU_FIRST_POLICIES:
        context.MAIN_MODEL_BOOT_PROFILE = selection_policy["cpu_profile"]
    observer = load_yaml_mapping(context.APP_CONFIG_ROOT / "configs/services.yaml")["services"]["host_resource_observer"]
    reader = resource_reader or AdaptiveResourceReader(
        f"http://{observer['compose_service']}:{observer['container_port']}", context.RUNTIME_CONTROLLER_TOKEN
    )
    state = context._state_store.read()
    if seed in CPU_FIRST_POLICIES and state.get("active_profile") not in {None, *context._catalog.profiles}:
        def recover_missing_artifact(value):
            value.update(active_profile=None, gate="closed")
            operation = value.get("last_operation") or {}
            if operation and operation.get("status") not in {"completed", "failed", "rollback_failed"}:
                operation.update(status="failed", error="GPU_ARTIFACT_UNAVAILABLE")
                for item in value.get("operations", []):
                    if item.get("id") == operation.get("id"):
                        item.update(operation)
        state = context._state_store.update(recover_missing_artifact)
    if not state.get("runtime_selection"):
        context._state_store.update(lambda s: s.update(runtime_selection={
            "mode": seed, "reason_code": "STARTING_CPU" if seed in RECOVERING_POLICIES else "OPERATOR_SELECTED",
        }))
    context._state_store.update(lambda s: s["runtime_selection"].update(cpu_profile=selection_policy["cpu_profile"], gpu_profile=selection_policy["gpu_profile"]))
    engine = main_model_backend or ManagedDockerBackend(
        context.DOCKER_SOCKET, context.COMPOSE_PROJECT,
        gateway_url=context._CONFIG.gateway_internal_url,
        internal_token=context.RUNTIME_CONTROLLER_TOKEN,
        config_root=context.APP_CONFIG_ROOT, cpu_cache_dir=Path("/models"),
        resource_reader=reader, selection_policy=selection_policy, gpu_policies=gpu_policies,
    )
    if isinstance(engine, ManagedDockerBackend):
        def recovering_operation(profile=None):
            current = context._state_store.read()
            operation = current.get("last_operation") or {}
            pending = operation.get("execution_policy") if (
                operation.get("status") not in {"completed", "failed", "rollback_failed"}
                and (profile is None or profile.profile_id == operation.get("requested_profile"))
            ) else None
            return (pending or (current.get("runtime_selection") or {}).get("mode")) in RECOVERING_POLICIES
        engine.uses_gpu_admission = recovering_operation
    assignment = gpu_policies.restore((state.get("runtime_selection") or {}).get("gpu_assignment"))
    if assignment is not None and (state.get("runtime_selection") or {}).get("mode") in RECOVERING_POLICIES:
        context._catalog.profiles[assignment.profile.profile_id] = assignment.profile
        if hasattr(engine, "bind_gpu"):
            engine.bind_gpu(assignment)
    context._main_model_manager = MainModelManager(
        context._catalog,
        context._state_store,
        engine,
        boot_profile=context.MAIN_MODEL_BOOT_PROFILE,
        profile_locked=context.MAIN_MODEL_PROFILE_LOCKED,
        idempotency_ttl_seconds=(
            float(context.MAIN_MODEL_SWITCH_IDEMPOTENCY_TTL_SECONDS)
            if context.MAIN_MODEL_SWITCH_IDEMPOTENCY_TTL_SECONDS
            else None
        ),
    )
    context._MAIN_SERVICE = str(context._catalog.runtime["compose_service"])
    context._initialization_error: str | None = None
    context._initialized = asyncio.Event()
    # 백그라운드 task가 실행 도중 가비지 컬렉션되지 않도록 strong reference를 유지한다
    # (asyncio는 스케줄된 task에 대해 weak reference만 유지한다).
    context._BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
    # 두 activation이 동시에 통과할 수 없도록 GPU-budget admission 판단을 직렬화한다.
    context._budget_lock = asyncio.Lock()
    context._adaptive_control = AdaptiveMainModelControl(
        context._main_model_manager, selection_policy, reader, gpu_policies=gpu_policies,
        admit_gpu=lambda fraction: _admit_profile_switch_or_raise(fraction),
    )
    context._adaptive_control.mutation_lock = context._budget_lock


    def _reserved_or_unavailable(service: str, status: str) -> bool:
        """자원 해제가 확인되지 않았을 때 GPU 여유량을 임의로 늘리지 않는다."""
        try:
            return gpu_reservation_active(status)
        except ValueError as exc:
            raise HTTPException(
                503, detail=f"cannot confirm GPU reservation for {service}: Docker state {status!r}"
            ) from exc


    async def _docker_reservation_status(service: str) -> str:
        """Docker 조회 장애를 예약 해제로 추정하지 않고 사용 불가로 반환한다."""
        try:
            return await context._executor().status(service)
        except Exception as exc:  # noqa: BLE001 - Docker 관측 실패는 Admission 차단 사유다
            raise HTTPException(
                503, detail=f"cannot observe GPU reservation for {service}"
            ) from exc


    async def _observe_budget_participants() -> tuple[list[Participant], dict[str, str]]:
        """GPU 예약 참여자와 원본 Docker 상태를 하나의 관측 집합으로 구성한다."""
        participants: list[Participant] = []
        observed: dict[str, str] = {}
        for service, fraction in context._VRAM_FRACTION.items():
            status = await _docker_reservation_status(service)
            observed[service] = status
            criticality = context._CRITICALITY.get(service, "")
            priority, evictable = _eviction_policy(criticality)
            participants.append(
                Participant(
                    key=service,
                    vram_fraction=fraction,
                    active=_reserved_or_unavailable(service, status),
                    priority=priority,
                    # paused/restarting은 VRAM을 점유하지만 안전한 자동 Stop 대상은 아니다.
                    evictable=evictable and status == "running",
                    criticality=criticality or None,
                )
            )
        snapshot = context._main_model_manager.snapshot()
        active_profile = snapshot.get("active_profile") or {}
        # 아직 active profile이 기록되지 않았을 때는 boot profile 예약값을 사용한다.
        boot_fraction = context._catalog.profiles[context._main_model_manager.boot_profile].vram_fraction
        fraction = active_profile.get("vram_fraction")
        main_fraction = float(boot_fraction if fraction is None else fraction)
        main_status = await _docker_reservation_status(context._MAIN_SERVICE)
        if (snapshot.get("runtime_state") == "stopped"
            and (snapshot.get("runtime_selection") or {}).get("mode") in RECOVERING_POLICIES
            and not _reserved_or_unavailable(context._MAIN_SERVICE, main_status)):
            main_fraction = 0.0
        observed[context._MAIN_SERVICE] = main_status
        participants.append(
            Participant(
                key=context._MAIN_SERVICE,
                vram_fraction=main_fraction,
                gpu_required=main_fraction > 0,
                active=_reserved_or_unavailable(context._MAIN_SERVICE, main_status),
                priority=context._MAIN_PRIORITY,
                evictable=False,
                criticality="primary_user_path",
            )
        )
        return participants, observed


    async def _build_participants() -> list[Participant]:
        return (await _observe_budget_participants())[0]


    async def _runtime_transition_plan(
        service: str,
        desired_state: str,
        *,
        force: bool,
    ) -> dict[str, Any]:
        """현재 Docker/GPU snapshot에서 side-effect 없이 runtime transition을 계획한다."""
        if context._main_model_manager.switch_in_progress():
            raise HTTPException(409, detail={"code": "MODEL_SWITCH_IN_PROGRESS", "message": "Wait for the current model operation."})
        if service == "main":
            target_key = context._MAIN_SERVICE
            prerequisites: list[str] = []
        elif service in context.CONTROLLABLE:
            target_key = service
            prerequisites = list(context._START_PREREQUISITES.get(service, []))
        else:
            raise HTTPException(403, detail=f"not controllable: {service}")

        participants, observed = await _observe_budget_participants()
        # 시작할 컨테이너가 없다면 GPU 퇴거를 승인하기 전에 계획 단계에서 거부한다.
        # not_found의 GPU 예약은 해제 상태이지만 새 Runtime을 생성할 권한은 없다.
        affected = [*prerequisites, target_key] if desired_state == "active" else [target_key]
        for key in dict.fromkeys(affected):
            if desired_state == "active" and observed[key] == "not_found":
                raise HTTPException(404, detail=f"container not found: {key}")
            # paused/restarting은 VRAM을 예약하지만 정상 기동도 안전한 Stop도 보장하지 않는다.
            # API가 성공할 수 없는 상태를 No-op 또는 적용 가능한 Plan으로 광고하지 않는다.
            if observed[key] in {"paused", "restarting"}:
                raise HTTPException(
                    409, detail=f"runtime {key} is {observed[key]}; resolve Docker state before transition"
                )
        plan = plan_runtime_transition(
            participants,
            target_key,
            desired_state,
            force=force,
            prerequisites=prerequisites,
            ceiling=context._GPU_BUDGET_CEILING,
        )
        response = plan.response()

        if service == "main":
            def alias(key: object) -> str:
                return "main" if str(key) == context._MAIN_SERVICE else str(key)

            response["target_key"] = "main"
            response["start"] = [alias(key) for key in response["start"]]
            response["stop"] = [alias(key) for key in response["stop"]]
            response["prerequisites"] = [alias(key) for key in response["prerequisites"]]
            for item in response["impact"]:
                item["key"] = alias(item.get("key"))
        return response




    def _validate_reviewed_plan(plan: dict[str, Any], plan_digest: str | None) -> None:
        if not is_valid_plan_digest(plan_digest):
            raise HTTPException(
                422,
                detail="plan_digest is required and must be a lowercase SHA-256 hex digest",
            )
        actual = str(plan.get("plan_digest") or "")
        if actual != plan_digest:
            raise HTTPException(
                409,
                detail={
                    "code": "RUNTIME_PLAN_CHANGED",
                    "message": "Runtime transition plan changed after review.",
                    "expected_plan_digest": plan_digest,
                    "actual_plan_digest": actual,
                },
            )
        if plan.get("admissible") is True:
            return
        detail: dict[str, Any] = {
            "code": "GPU_BUDGET_EXCEEDED",
            "message": "GPU budget does not allow this activation.",
            "feasible": not bool(plan.get("reason")),
        }
        budget = plan.get("budget") or {}
        before = budget.get("before") or {}
        detail["available"] = before.get("free")
        if plan.get("reason"):
            detail["reason"] = plan["reason"]
        if plan.get("stop"):
            detail["plan"] = {"stop": list(plan["stop"])}
        raise HTTPException(409, detail=detail)


    def _parse_runtime_plan_payload(payload: Any) -> tuple[str, bool]:
        if not isinstance(payload, dict):
            raise HTTPException(422, detail="request body must be a JSON object")
        unknown = sorted(set(payload) - {"desired_state", "force"})
        if unknown:
            raise HTTPException(422, detail=f"unsupported fields: {unknown}")
        desired_state = payload.get("desired_state")
        if desired_state not in {"active", "stopped"}:
            raise HTTPException(422, detail="desired_state must be 'active' or 'stopped'")
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise HTTPException(422, detail="force must be a boolean")
        return desired_state, force


    async def _admit_profile_switch_or_raise(target_fraction: float) -> None:
        """Main Model Profile 전환의 예약량 변경을 보수적으로 검사한다.

        Runtime 시작·중지의 Plan/Apply는 _runtime_transition_plan만 사용한다.
        이 함수는 Profile 교체의 다른 VRAM 비용을 별도로 검증하며 자동 퇴거하지 않는다.
        """
        if target_fraction == 0:
            # CPU RAM·Artifact 준비는 Backend가 검사하며 GPU 관측 장애로 막지 않는다.
            return
        participants = await _build_participants()
        result = plan_activation(
            participants, context._MAIN_SERVICE, target_fraction, ceiling=context._GPU_BUDGET_CEILING
        )
        if result.already_fits:
            return
        detail: dict[str, Any] = {
            "code": "GPU_BUDGET_EXCEEDED",
            "message": "GPU budget does not allow this activation.",
            "feasible": result.feasible,
            "required": round(result.required, 4),
            "available": round(result.available, 4),
            "ceiling": result.ceiling,
        }
        if result.feasible:
            detail["plan"] = {"stop": list(result.victims)}
        else:
            detail["reason"] = result.reason
        raise HTTPException(409, detail=detail)


    async def _apply_reviewed_activation(service: str, plan: dict[str, Any], *, force: bool) -> list[str]:
        """하나의 Planner 계약으로 상태를 재확인한 뒤 검토된 Victim만 중지한다.

        Docker는 Controller 외부에서도 변경될 수 있다. 변경 실행 직전 같은
        Transition Planner를 재관측하고 Digest가 바뀌면 중지하지 않는다.
        별도 Admission 계산을 두지 않으며 로컬 context._budget_lock 안에서 호출한다.
        """
        fresh = await _runtime_transition_plan(service, "active", force=force)
        _validate_reviewed_plan(fresh, str(plan["plan_digest"]))
        stopped: list[str] = []
        for victim in fresh["stop"]:
            if victim not in context.CONTROLLABLE:
                raise HTTPException(503, detail=f"uncontrollable eviction target: {victim}")
            if not await context._executor().stop(victim):
                raise HTTPException(503, detail=f"cannot stop planned GPU eviction target: {victim}")
            stopped.append(victim)
        return stopped


    async def _require_runtime_controller_token(authorization: str | None = Header(default=None)) -> None:
        # 토큰 없이 여기 도달할 수 있는 경우는 운영자가 INTERNAL_SERVICE_AUTH_REQUIRED로
        # 내부 인증 없음을 선언한 구성뿐이다(auth profile local_open).
        # 선언과 어긋난 빈 토큰은 load_runtime_controller_config가 기동 시점에 이미 거부한다.
        if not context._CONFIG.internal_service_auth_required:
            return
        if authorization != f"Bearer {context.RUNTIME_CONTROLLER_TOKEN}":
            raise HTTPException(401, detail="invalid internal service token")


    async def _run_initialize() -> None:
        try:
            # 프로젝트 Label 없이 실행하면 같은 서비스 이름을 쓰는 다른 Compose 프로젝트까지
            # Docker 검색 권한이 넓어지므로 허용하지 않는다.
            require_compose_project(context.COMPOSE_PROJECT)
            await context._main_model_manager.initialize()
        except Exception as exc:  # noqa: BLE001 - /health를 통해 노출되며, 루프를 죽여서는 안 된다
            context._initialization_error = str(exc)
            if (context._state_store.read().get("runtime_selection") or {}).get("mode") in RECOVERING_POLICIES:
                context._main_model_manager.record_initialization_failure(str(exc))
        finally:
            context._initialized.set()


    # main-llm-vllm이 Runtime Controller 제어 API를 거치지 않고 재시작됐는지(예: 운영자의 수동
    # `docker restart`) 주기적으로 감지하는 간격. 매 tick마다 lock 획득 + Docker inspect
    # 호출 하나뿐이라 부담이 사실상 없어서, 놓치는 창을 줄이는 쪽으로 짧게 잡았다.
    context._RECONCILE_POLL_INTERVAL_SECONDS = selection_policy["poll_interval_seconds"]


    async def _run_reconciliation_loop() -> None:
        # reconcile_if_restarted() 자체가 예상 가능한 실패(inspect 실패 등)는 내부에서
        # 처리하고 다음 tick으로 넘어가므로, 여기서 잡히는 예외는 프로그래밍 오류에
        # 가깝다. 그래도 루프를 죽이지 않는다 — 죽으면 이후 재시작 감지가 프로세스
        # 수명 내내 영구히 멈춘다.
        while True:
            await asyncio.sleep(context._RECONCILE_POLL_INTERVAL_SECONDS)
            try:
                if (context._state_store.read().get("runtime_selection") or {}).get("mode") in RECOVERING_POLICIES:
                    await context._adaptive_control.step()
                else:
                    await context._main_model_manager.reconcile_if_restarted()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("main-model reconciliation tick failed: %s", exc)


    async def _run_log_target_projection_loop() -> None:
        while True:
            try:
                target_count = await _refresh_log_targets()
                _logger.debug("refreshed Alloy log targets: count=%s", target_count)
            except Exception as exc:  # noqa: BLE001 - monitoring failure must not affect serving
                _logger.warning("log target projection tick failed: %s", exc)
            await asyncio.sleep(context.LOG_TARGET_REFRESH_SECONDS)


    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        del app
        # main-model reconciliation은 main-llm 런타임이 healthy 상태가 될 때까지
        # 최대 startup_timeout_seconds(600초)까지 블록될 수 있다. 여기서 이를 await하면
        # uvicorn의 시작이 지연되어, cold deploy 시 컨테이너의 약 40초 healthcheck
        # 예산을 넘겨 /health에 도달할 수 없게 되고 -> Runtime Controller가 unhealthy로 표시되어
        # Gateway의 depends_on(service_healthy)이 전체 rollout을 실패시킨다.
        # Runtime Controller는 control plane이다: 그 liveness는 main-llm 부팅과 무관하며,
        # main-llm 부팅 상태는 대신 gate(Gateway가 읽는다)로 추적된다.
        init_task = asyncio.create_task(_run_initialize())
        context._BACKGROUND_TASKS.add(init_task)
        init_task.add_done_callback(context._BACKGROUND_TASKS.discard)
        # 이 루프는 initialize()와 달리 main-llm이 healthy해지길 기다리지 않는다 —
        # 주기적으로 대기하고 관측할 뿐이므로 Runtime Controller startup을 지연시키지 않는다.
        reconcile_task = asyncio.create_task(_run_reconciliation_loop())
        context._BACKGROUND_TASKS.add(reconcile_task)
        reconcile_task.add_done_callback(context._BACKGROUND_TASKS.discard)
        log_target_task = asyncio.create_task(_run_log_target_projection_loop())
        context._BACKGROUND_TASKS.add(log_target_task)
        log_target_task.add_done_callback(context._BACKGROUND_TASKS.discard)
        try:
            yield
        finally:
            init_task.cancel()
            reconcile_task.cancel()
            log_target_task.cancel()
            # App이 시작한 작업의 취소 완료를 확인한다. Manager의 영속 모델 전환
            # Task는 별도 복구 계약을 가지므로 이 수명주기에서 임의로 취소하지 않는다.
            await asyncio.gather(init_task, reconcile_task, log_target_task, return_exceptions=True)


    # --------------------------------------------------------------------- app

    app = FastAPI(
        title="Runtime Controller",
        description="Internal runtime lifecycle and Main Model control plane. Not exposed publicly.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )


    @app.get("/health")
    async def health() -> dict[str, str]:
        # control-plane의 liveness는 main-llm 부팅과 의도적으로 분리되어 있다.
        # reconciliation이 진행 중인 동안에는 Runtime Controller가 healthy 상태를 유지하고
        # gate는 닫힌 채로 있다(Gateway는 local-main에 대해 fail closed된다). 오직
        # *확정적인* reconciliation 실패만 unhealthy로 노출된다.
        if context._initialized.is_set() and context._initialization_error:
            state = context._state_store.read()
            if context.COMPOSE_PROJECT and (
                state.get("gate") == "open" or state.get("runtime_state") == "stopped"
            ):
                # 초기 실패 뒤 Main 재검증 또는 명시적 중지가 수렴했으면 과거 오류가
                # Controller를 영구 unhealthy로 남기지 않는다. Gate의 개방 권위는 Manager다.
                context._initialization_error = None
                return {"status": "ok"}
            if (state.get("runtime_selection") or {}).get("mode") not in RECOVERING_POLICIES:
                raise HTTPException(503, detail=f"main model reconciliation failed: {context._initialization_error}")
        return {"status": "ok"}


    @app.get("/containers/status")
    async def containers_status(authorization: str | None = Header(default=None)) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        statuses: dict[str, str] = {}
        for service in context.CONTROLLABLE:
            try:
                statuses[service] = await context._executor().status(service)
            except Exception as exc:
                statuses[service] = f"error: {exc}"
        return JSONResponse({"containers": statuses})


    @app.get("/gpu-budget")
    async def gpu_budget(authorization: str | None = Header(default=None)) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        participants = await _build_participants()
        return JSONResponse(budget_snapshot(participants, ceiling=context._GPU_BUDGET_CEILING))


    @app.post("/runtime-transitions/{service}/plan")
    async def runtime_transition_plan(
        service: str,
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        desired_state, force = _parse_runtime_plan_payload(payload)
        async with context._budget_lock:
            plan = await _runtime_transition_plan(service, desired_state, force=force)
        return JSONResponse(plan)


    @app.get("/main-model")
    async def main_model(
        authorization: str | None = Header(default=None),
        observed: bool = True,
    ) -> JSONResponse:
        """활성 main-model 상태를 반환한다.

        ``observed=false``는 control-plane ledger만 읽고 Docker 관측(`observed_runtime`)을
        건너뛴다. ledger 필드(gate, active_profile, runtime_state, stats, last_operation)만
        필요한 호출자를 위한 것이다 -- 특히 Gateway는 chat 요청마다 gate를 확인하므로,
        기본 경로를 쓰면 추론 요청 하나하나가 Docker API 호출 두 번(list + inspect)에
        직렬로 묶인다. 그러면 Docker daemon이 흔들릴 때 실제 런타임은 멀쩡한데도 모든
        chat이 MAIN_MODEL_CONTROL_UNAVAILABLE로 떨어진다.

        기본값은 ``True``이므로 `GET /admin/main-model`의 기존 응답 형태는 그대로다.
        """
        await _require_runtime_controller_token(authorization)
        try:
            # jsonable_encoder는 date/datetime(및 그 외 JSON 네이티브가 아닌 타입)을
            # 직렬화 가능한 형태로 변환한다. 이것이 없으면 profile catalog 안의 date
            # 값 하나(예: quote되지 않은 validated_at)만으로도 이 엔드포인트가 500을
            # 반환하게 되고, Gateway는 이를 RuntimeControllerUnavailable로 인식하여 모든
            # main-model 요청을 실패시킨다.
            snapshot = (
                await context._main_model_manager.observed_snapshot()
                if observed
                else context._main_model_manager.snapshot()
            )
            return JSONResponse(jsonable_encoder(snapshot))
        except MainModelStateError as exc:
            raise HTTPException(503, detail=str(exc)) from exc


    @app.get("/main-model/profiles")
    async def main_model_profiles(authorization: str | None = Header(default=None)) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        # 정책 판정은 실제 전환 요청과 같은 Manager 검사를 사용한다.
        # GPU 예산도 기존 Admission을 사용하며 관측 실패를 "여유"로 해석하지 않는다.
        async with context._budget_lock:
            profiles = context._main_model_manager.profiles()
            switching = context._main_model_manager.switch_in_progress()
            eligible = [
                profile for profile in profiles
                if not profile["active"]
                and not switching
                and profile.get("runtime_backend") != "llama-cpp"
                and context._main_model_manager.switch_policy_error(profile["id"]) is None
            ]
            participants = None
            if eligible:
                try:
                    # Gateway 측 내부 Controller 조회 제한 시간(5초)보다 먼저
                    # 관측을 종료해 화면에는 전체 오류 대신 '판단 불가'를 제공한다.
                    participants = await asyncio.wait_for(_build_participants(), timeout=3.0)
                except Exception as exc:  # noqa: BLE001 - 실패는 모든 후보에 판단 불가로 투영
                    _logger.warning("GPU admission preflight observation unavailable: %s", type(exc).__name__)
            for profile in profiles:
                policy_error = context._main_model_manager.switch_policy_error(profile["id"])
                profile["switch_preflight"] = project_switch_preflight(
                    active=profile["active"],
                    policy_error_code=policy_error.code if policy_error else None,
                    switch_in_progress=switching,
                    participants=participants,
                    target_key=context._MAIN_SERVICE,
                    target_fraction=profile["vram_fraction"],
                    ceiling=context._GPU_BUDGET_CEILING,
                )
            return JSONResponse(jsonable_encoder({"profiles": profiles}))


    @app.post("/main-model/switch", status_code=202)
    async def switch_main_model(
        payload: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        unknown = set(payload) - {"profile", "confirm_unverified", "request_id", "execution_policy", "server_limits"}
        if unknown:
            raise HTTPException(422, detail=f"unsupported fields: {sorted(unknown)}")
        mode = payload.get("execution_policy")
        if "execution_policy" in payload and mode not in EXECUTION_POLICIES:
            raise HTTPException(422, detail="invalid execution_policy")
        profile_id = str(payload.get("profile", ""))
        limits = payload.get("server_limits")
        if limits is not None and (
            not isinstance(limits, dict)
            or set(limits) != {"context_tokens", "max_output_tokens"}
        ):
            raise HTTPException(422, detail="server_limits requires context_tokens and max_output_tokens")
        target_profile = context._catalog.profiles.get(profile_id)
        if limits is not None:
            stored = context._state_store.read().get("runtime_limit_profiles") or {}
            base_id = (stored.get(profile_id) or {}).get("base_profile", profile_id)
            try:
                target_profile = build_runtime_limit_profile(
                    context._catalog, base_id,
                    limits["context_tokens"], limits["max_output_tokens"],
                )
            except RuntimeLimitError as exc:
                raise HTTPException(422, detail=str(exc)) from exc
            if not context._catalog.runtime.get("adaptive"):
                raise HTTPException(422, detail="server_limits editing requires a managed Runtime Controller")
            if payload.get("confirm_unverified") is not True:
                raise HTTPException(409, detail="custom server limits require explicit unverified confirmation")
        try:
            async with context._budget_lock:
                selected_mode = mode or ("cpu" if target_profile and target_profile.runtime_backend == "llama-cpp" else "gpu")
                if selected_mode in RECOVERING_POLICIES and profile_id != selection_policy["cpu_profile"]:
                    raise HTTPException(422, detail="fallback/automatic policy starts with the default CPU profile")
                if selected_mode == "cpu" and (
                    target_profile is None or target_profile.runtime_backend != "llama-cpp"
                ):
                    raise HTTPException(422, detail="CPU policy requires a CPU profile")
                if selected_mode == "gpu" and target_profile and target_profile.runtime_backend == "llama-cpp":
                    raise HTTPException(422, detail="GPU policy requires a GPU profile")
                if selected_mode in RECOVERING_POLICIES and payload.get("confirm_unverified") is not True:
                    gpu = context._catalog.profiles.get(selection_policy["gpu_profile"])
                    if gpu is None or gpu.qualification.get("status") != "verified":
                        raise HTTPException(409, detail={"code": "MODEL_PROFILE_CONFIRMATION_REQUIRED", "message": "Confirm the automatic GPU candidate before enabling automatic policy."})
                if selected_mode in RECOVERING_POLICIES and context.MAIN_MODEL_PROFILE_LOCKED:
                    raise HTTPException(409, detail="MODEL_PROFILE_LOCKED")
                # target profile이 GPU를 초과 사용하게 될 경우 (eviction plan과 함께) 거부한다.
                # 같거나 더 작은 profile로 전환하면 main slot에 그대로 들어맞지만, 더 큰 profile은
                # 운영자에게 먼저 무엇을 stop해야 하는지 알려준다. (여기서는 auto-evict를 하지
                # 않는다: profile 변경은 의도적인 행위이므로, 공간 확보는 명시적인 단계여야 한다.)
                if target_profile is not None:
                    # 사전 판단과 동일하게 기술·명시적 리소스 정책을 먼저 확인한다.
                    # 확실히 거부할 요청에서 Docker GPU 관측을 수행하지 않는다.
                    policy_error = context._main_model_manager.switch_policy_error(
                        base_id if limits is not None else profile_id
                    )
                    if policy_error is not None:
                        raise policy_error
                    await _admit_profile_switch_or_raise(target_profile.vram_fraction)
                if limits is not None:
                    outcome = context._main_model_manager.request_limit_switch(
                        profile_id,
                        context_tokens=limits["context_tokens"],
                        max_output_tokens=limits["max_output_tokens"],
                        confirm_unverified=True,
                        client_request_id=payload.get("request_id"),
                        execution_policy=selected_mode,
                    )
                else:
                    outcome = context._main_model_manager.request_switch(
                        profile_id,
                        confirm_unverified=payload.get("confirm_unverified") is True,
                        client_request_id=payload.get("request_id"),
                        execution_policy=selected_mode,
                    )
        except MainModelSwitchError as exc:
            raise HTTPException(
                exc.status_code,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        # 스스로 설명하는 응답: operation의 실제 상태를 보고한다(새 switch는 "pending"이고,
        # idempotent replay는 이전 operation의 상태를 그대로 갖는다) 그리고 새로운 switch가
        # 실제로 시작되었는지, 어디서 확인할 수 있는지를 명확히 알려준다.
        operation = context._main_model_manager.operation(outcome.operation_id) or {}
        status = str(operation.get("status", "pending"))
        if outcome.reused:
            message = (
                f"request_id was already used; returning the existing operation "
                f"(status: {status}). No new switch was started — send a unique "
                f"request_id (or omit it) to start a new switch."
            )
        else:
            message = (
                "Switch accepted. Watch progress at "
                f"GET /admin/main-model/operations/{outcome.operation_id} or "
                "GET /admin/main-model (last_operation)."
            )
        return JSONResponse(
            {
                "operation_id": outcome.operation_id,
                "status": status,
                "reused": outcome.reused,
                "message": message,
            },
            status_code=202,
        )


    @app.get("/main-model/operations")
    async def main_model_operations(
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        return JSONResponse({"items": context._main_model_manager.operations()})


    @app.get("/main-model/operations/{operation_id}")
    async def main_model_operation(
        operation_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        operation = context._main_model_manager.operation(operation_id)
        if operation is None:
            raise HTTPException(404, detail="operation not found")
        return JSONResponse(operation)


    @app.post("/main-model/stop")
    async def main_model_stop(
        plan_digest: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """VRAM 회수를 위해 main runtime을 drain 후 중지하고 chat 요청은 fail-closed 처리한다."""
        await _require_runtime_controller_token(authorization)
        async with context._budget_lock:
            plan = await _runtime_transition_plan("main", "stopped", force=False)
            _validate_reviewed_plan(plan, plan_digest)
            await context._main_model_manager.stop_main(strict_drain=True)
        return JSONResponse({"action": "stop", "service": context._MAIN_SERVICE, "runtime_state": "stopped"})


    @app.post("/main-model/start")
    async def main_model_start(
        force: bool = False,
        plan_digest: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        """GPU 예산을 확인한 뒤 main runtime을 시작하고 검증한다."""
        await _require_runtime_controller_token(authorization)
        async with context._budget_lock:
            plan = await _runtime_transition_plan("main", "active", force=force)
            _validate_reviewed_plan(plan, plan_digest)
            evicted = await _apply_reviewed_activation("main", plan, force=force)
            if (context._state_store.read().get("runtime_selection") or {}).get("mode") in RECOVERING_POLICIES and not plan["no_op"]:
                outcome = context._main_model_manager.request_switch(selection_policy["cpu_profile"], confirm_unverified=True)
                result = await context._main_model_manager.wait_for_operation(outcome.operation_id)
                if result["status"] != "completed":
                    raise HTTPException(503, detail="CPU startup verification failed")
            else:
                await context._main_model_manager.start_main()
        return JSONResponse(
            {"action": "start", "service": context._MAIN_SERVICE, "runtime_state": "active", "evicted": evicted}
        )


    @app.post("/containers/{service}/stop")
    async def stop_container(
        service: str,
        plan_digest: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        if service not in context.CONTROLLABLE:
            raise HTTPException(403, detail=f"not controllable: {service}")
        async with context._budget_lock:
            plan = await _runtime_transition_plan(service, "stopped", force=False)
            _validate_reviewed_plan(plan, plan_digest)
            # 검토한 Plan이 No-op이면 Docker Stop 호출로 의미를 바꾸지 않는다.
            # not_found/exited 모두 이미 GPU 예약이 해제돼 있는 상태다.
            stopped: list[str] = []
            if plan["stop"]:
                if not await context._executor().stop(service):
                    raise HTTPException(404, detail=f"container not found: {service}")
                stopped.append(service)
        return JSONResponse({"action": "stop", "service": service, "stopped": stopped})


    @app.post("/containers/{service}/start")
    async def start_container(
        service: str,
        force: bool = False,
        plan_digest: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await _require_runtime_controller_token(authorization)
        if service not in context.CONTROLLABLE:
            raise HTTPException(403, detail=f"not controllable: {service}")

        started: list[str] = []
        evicted: list[str] = []

        async with context._budget_lock:
            plan = await _runtime_transition_plan(service, "active", force=force)
            _validate_reviewed_plan(plan, plan_digest)
            # 동일한 Runtime Planner로 재관측하여 검토한 Plan과의 일치를 확인한다.
            # GPU 예약량·기동 대상·선행 서비스 보호·퇴거 순위는 Planner 한 곳이 소유한다.
            evicted = await _apply_reviewed_activation(service, plan, force=force)

            # prerequisite들을 순서대로 시작한다(GPU 메모리 프로파일링을 순차적으로 진행).
            for prereq in context._START_PREREQUISITES.get(service, []):
                prereq_url = context._HEALTH_URL[prereq]
                status = await context._executor().status(prereq)
                if status == "running":
                    continue
                if not await context._executor().start(prereq):
                    raise HTTPException(503, detail=f"prerequisite container not found: {prereq}")
                if not await context._wait_healthy(prereq, prereq_url):
                    raise HTTPException(
                        503, detail=f"prerequisite {prereq} did not become healthy within timeout"
                    )
                started.append(prereq)

            if await context._executor().status(service) == "not_found":
                raise HTTPException(404, detail=f"container not found: {service}")
            if await context._executor().status(service) != "running":
                if not await context._executor().start(service):
                    raise HTTPException(404, detail=f"container not found: {service}")
                started.append(service)
            target_url = context._HEALTH_URL[service]
            if not await context._wait_healthy(service, target_url):
                raise HTTPException(
                    503, detail=f"container {service} did not become healthy within timeout"
                )

        return JSONResponse(
            {"action": "start", "service": service, "started": started, "evicted": evicted}
        )

    context.app = app
    app.state.controller = context
    context.health = health
    context.gpu_budget = gpu_budget
    context._build_participants = _build_participants
    context._runtime_transition_plan = _runtime_transition_plan
    context._run_initialize = _run_initialize
    context.main_model_start = main_model_start
    context.start_container = start_container
    context.stop_container = stop_container
    return app
