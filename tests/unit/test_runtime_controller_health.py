"""Runtime Controller healthcheck에 대한 회귀 가드.

예전에 Runtime Controller가 lifespan startup 안에서 main-model reconciliation을 기다리다가
(startup_timeout_seconds까지, 600초) 콜드 배포가 롤백된 적이 있다. uvicorn은
startup이 끝나기 전엔 요청을 받지 않으므로, /health가 컨테이너의 ~40초
healthcheck 예산을 넘도록 응답 불가 상태였고, Runtime Controller는 unhealthy로 표시되어
Gateway의 depends_on(service_healthy)가 전체 롤아웃을 실패시켰다. Runtime Controller는
control plane이다: 그 liveness는 main-llm 부팅(gate가 따로 추적한다)과
독립적이어야 한다.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from fastapi import HTTPException
from tests.support.asgi import InlineASGITestClient as TestClient


def _load_runtime_controller(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    import ai_model_serving.apps.runtime_controller as runtime_controller

    return importlib.reload(runtime_controller)


def test_lifespan_does_not_block_health_on_main_model_reconciliation(tmp_path, monkeypatch):
    controller = _load_runtime_controller(tmp_path, monkeypatch)

    async def slow_initialize() -> None:
        # validate()가 컨테이너의 healthcheck 예산을 훨씬 넘겨 main-llm health를
        # 기다리는 상황을 시뮬레이션한다. startup이 이걸 await했다면 TestClient의
        # __enter__(lifespan startup을 실행함)가 블록되어 테스트가 멈췄을 것이다.
        await asyncio.sleep(3600)

    monkeypatch.setattr(controller._main_model_manager, "initialize", slow_initialize)

    with TestClient(controller.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        # reconciliation은 아직 진행 중이다: 완료도 에러도 아니다.
        assert not controller._initialized.is_set()


def test_initialization_fails_closed_without_compose_project(tmp_path, monkeypatch):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "COMPOSE_PROJECT", "")

    asyncio.run(controller._run_initialize())

    assert controller._initialized.is_set()
    assert "COMPOSE_PROJECT is required" in (controller._initialization_error or "")


def test_health_surfaces_definitive_reconciliation_failure(tmp_path, monkeypatch):
    controller = _load_runtime_controller(tmp_path, monkeypatch)

    async def failing_initialize() -> None:
        raise RuntimeError("main runtime did not become healthy")

    monkeypatch.setattr(controller._main_model_manager, "initialize", failing_initialize)

    # reconciliation이 끝나지 않은 동안에는 Runtime Controller가 healthy 상태를 유지한다.
    assert asyncio.run(controller.health()) == {"status": "ok"}

    # 백그라운드 initializer는 실패를 기록하되 task 밖으로 예외를 던지지 않는다
    # (그리고 완료 이벤트는 항상 set한다).
    asyncio.run(controller._run_initialize())
    assert controller._initialized.is_set()
    assert "main runtime did not become healthy" in (controller._initialization_error or "")

    # 이제 확정된 실패는 unhealthy로 드러난다.
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(controller.health())
    assert excinfo.value.status_code == 503
    assert "main runtime did not become healthy" in str(excinfo.value.detail)


def test_runtime_controller_reads_canonical_main_model_env(tmp_path):
    from pathlib import Path

    from ai_model_serving.apps.runtime_controller import load_runtime_controller_config

    config = load_runtime_controller_config(
        {
            "APP_CONFIG_ROOT": str(Path(".").resolve()),
            "MAIN_MODEL_STATE_PATH": str(tmp_path / "state.json"),
            "INTERNAL_SERVICE_AUTH_REQUIRED": "false",
            "MAIN_MODEL_BOOT_PROFILE": "gemma4-12b-unified-fp8",
            "MAIN_MODEL_PROFILE_LOCKED": "true",
            "MAIN_MODEL_SWITCH_IDEMPOTENCY_TTL_SECONDS": "30",
        }
    )
    assert config.boot_profile == "gemma4-12b-unified-fp8"
    assert config.profile_locked is True
    assert config.idempotency_ttl_seconds == "30"

def test_runtime_controller_refuses_to_start_when_declared_internal_auth_has_no_token(tmp_path):
    """가장 높은 권한을 가진 프로세스는 인증을 조용히 끄지 않아야 한다.

    예전에는 인증 활성 여부를 토큰 문자열이 비었는지로 판단했다. 그래서
    private_network/strict처럼 내부 인증을 요구한 구성에서 토큰이 유실되면
    Docker socket을 쥔 Runtime Controller가 거부 대신 무인증 서비스를 택했다. 판단 근거를
    운영자가 선언한 INTERNAL_SERVICE_AUTH_REQUIRED로 옮긴다.
    """
    from pathlib import Path

    from ai_model_serving.apps.runtime_controller import load_runtime_controller_config

    base = {"APP_CONFIG_ROOT": str(Path(".").resolve()), "MAIN_MODEL_STATE_PATH": str(tmp_path / "s.json")}

    for missing_token in ({}, {"INTERNAL_SERVICE_TOKEN": ""}, {"INTERNAL_SERVICE_TOKEN": "change-me-internal"}):
        with pytest.raises(RuntimeError, match="INTERNAL_SERVICE_TOKEN"):
            load_runtime_controller_config({**base, "INTERNAL_SERVICE_AUTH_REQUIRED": "true", **missing_token})

    # 선언이 없거나 인증 없음을 선언한 구성은 지금 동작을 유지한다. auth profile
    # local_open이 내부 인증 없음을 명시하는 정당한 배포다.
    for declared in ({}, {"INTERNAL_SERVICE_AUTH_REQUIRED": "false"}):
        config = load_runtime_controller_config({**base, **declared})
        assert config.internal_service_token == ""
        assert config.internal_service_auth_required is False

    admitted = load_runtime_controller_config(
        {**base, "INTERNAL_SERVICE_AUTH_REQUIRED": "true", "INTERNAL_SERVICE_TOKEN": "real-internal-token"}
    )
    assert admitted.internal_service_token == "real-internal-token"




@pytest.mark.parametrize(("docker_state", "reserved"), [
    ("running", True), ("paused", True), ("restarting", True),
    ("created", False), ("exited", False), ("not_found", False),
])
def test_gpu_budget_uses_docker_reservation_not_serving_readiness(
    tmp_path, monkeypatch, docker_state, reserved
):
    # GPU 예산은 컨테이너가 요청을 처리할 수 있는지와 무관하게 예약을 보존한다.
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {"embedding-vllm": 0.20})

    class ObservedExecutor:
        async def status(self, service):
            return docker_state if service == "embedding-vllm" else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    participants = asyncio.run(controller._build_participants())
    secondary = next(p for p in participants if p.key == "embedding-vllm")
    assert secondary.active is reserved
    # 자동 퇴거에는 실제로 Running인 Runtime만 포함한다.
    assert secondary.evictable is (docker_state == "running")

    # 같은 상태는 운영 조회에도 실제 예약량으로 나타나야 한다.
    response = asyncio.run(controller.gpu_budget())
    import json
    ledger = json.loads(response.body)
    assert ledger["used"] == (0.20 if reserved else 0.0)


@pytest.mark.parametrize("docker_state", ["paused", "restarting"])
def test_reserved_but_not_running_runtime_cannot_be_activated_as_noop(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.20})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return docker_state if key == service else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    # Docker paused 상태의 Stop은 실패할 수 있다. 실행 불가능한 Stop Plan이나
    # 활성화 No-op을 발행하지 않고 운영자에게 Docker 상태 복구를 요구한다.
    for desired_state in ("active", "stopped"):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(controller._runtime_transition_plan(service, desired_state, force=False))
        assert raised.value.status_code == 409
        assert docker_state in str(raised.value.detail)


@pytest.mark.parametrize("docker_state", ["dead", "removing", "unknown"])
def test_unconfirmed_docker_state_denies_gpu_plan_and_budget(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.20})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return docker_state if key == service else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    with pytest.raises(HTTPException) as budget:
        asyncio.run(controller.gpu_budget())
    assert budget.value.status_code == 503
    with pytest.raises(HTTPException) as plan:
        asyncio.run(controller._runtime_transition_plan(service, "active", force=True))
    assert plan.value.status_code == 503


def test_paused_main_runtime_keeps_its_protected_gpu_reservation(tmp_path, monkeypatch):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.60})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return "paused" if key == controller._MAIN_SERVICE else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    participants = asyncio.run(controller._build_participants())
    main = next(p for p in participants if p.key == controller._MAIN_SERVICE)
    assert main.active is True
    assert main.evictable is False
    # 예약되어 있고 퇴거할 수 없는 main을 무시하고 secondary를 시작하지 않는다.
    plan = asyncio.run(controller._runtime_transition_plan(service, "active", force=True))
    assert plan["admissible"] is False


@pytest.mark.parametrize("docker_state", ["running", "paused", "restarting"])
def test_non_running_gpu_reservation_cannot_be_automatically_evicted(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    victim, target = sorted(controller.CONTROLLABLE)[:2]
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {victim: 0.25, target: 0.85})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {target: []})
    mutations: list[str] = []

    class ObservedExecutor:
        async def status(self, service):
            return docker_state if service == victim else "exited"

        async def stop(self, service):
            mutations.append(service)
            raise AssertionError("unapproved Docker mutation")

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    plan = asyncio.run(controller._runtime_transition_plan(target, "active", force=True))
    if docker_state == "running":
        assert plan["admissible"] is True
        assert plan["stop"] == [victim]
    else:
        assert plan["admissible"] is False
        assert plan["stop"] == []
        with pytest.raises(HTTPException) as rejected:
            asyncio.run(controller.start_container(
                target, force=True, plan_digest=plan["plan_digest"], authorization=None
            ))
        assert rejected.value.status_code == 409
        assert mutations == []
