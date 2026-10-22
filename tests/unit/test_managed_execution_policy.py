"""실행 정책은 배포 기능·권한과 독립적이며 공통 전환·GPU Admission을 따른다."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from ai_model_serving.apps.runtime_controller import create_runtime_controller_app
from tests.support.main_model import _SHARED_IMAGE
from tests.unit.test_adaptive_runtime import Backend, FREE, UNKNOWN

ROOT = Path(__file__).resolve().parents[2]
CPU = "cpu-gguf-text"
GPU = "gemma4-e4b-it"


def app(tmp_path, mode="automatic", *, image=_SHARED_IMAGE, resources=FREE, backend=None):
    async def reader():
        return resources

    class Executor:
        async def status(self, service):
            return "running" if service == "main-llm-vllm" else "exited"

    controller = create_runtime_controller_app(environment={
        "APP_CONFIG_ROOT": str(ROOT), "MAIN_MODEL_STATE_PATH": str(tmp_path / "state.json"),
        "COMPOSE_PROJECT": "managed-test", "VLLM_IMAGE": image,
        "MAIN_MODEL_BOOT_PROFILE": CPU, "MAIN_MODEL_EXECUTION_POLICY": mode,
    }, resource_reader=reader, executor=Executor(), main_model_backend=backend or Backend(observed=CPU)).state.controller
    controller.switch_main_model = next(route.endpoint for route in controller.app.routes if route.path == "/main-model/switch")
    return controller


async def switch(controller, mode, profile=CPU, **extra):
    response = await controller.switch_main_model({"profile": profile, "execution_policy": mode,
        "confirm_unverified": True, **extra}, authorization=None)
    operation = await controller._main_model_manager.wait_for_operation(json.loads(response.body)["operation_id"])
    assert operation["status"] == "completed"


def test_policy_change_preserves_supporting_features_and_survives_restart(tmp_path):
    async def scenario():
        controller = app(tmp_path)
        await controller._main_model_manager.initialize()
        services = controller.CONTROLLABLE
        assert services
        await switch(controller, "cpu")
        for now in (0, 10, 50, 100):
            await controller._adaptive_control.step(now=now)
        assert controller._main_model_manager.snapshot()["active_profile"]["id"] == CPU
        assert controller.CONTROLLABLE == services
        # .env seed를 automatic으로 남겨도 Console의 영속 CPU 선택이 우선한다.
        restarted = app(tmp_path, "automatic")
        assert restarted._state_store.read()["runtime_selection"]["mode"] == "cpu"
        await switch(controller, "automatic")
        for now in (110, 115, 120, 150):
            await controller._adaptive_control.step(now=now)
        operation = controller._state_store.read()["last_operation"]
        assert (await controller._main_model_manager.wait_for_operation(operation["id"]))["status"] == "completed"
        assert controller._main_model_manager.snapshot()["active_profile"]["id"] == GPU
        await switch(controller, "gpu", GPU)
        assert controller._state_store.read()["runtime_selection"]["mode"] == "gpu"
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["automatic", "fallback"])
def test_cpu_core_remain_available_without_gpu_artifact_or_observation(tmp_path, mode):
    async def scenario():
        controller = app(tmp_path, mode, image="not-built:local", resources=UNKNOWN)
        await controller._run_initialize()
        for now in (0, 30, 60):
            await controller._adaptive_control.step(now=now)
        value = controller._main_model_manager.snapshot()
        assert value["gate"] == "open" and value["active_profile"]["id"] == CPU
        assert controller.CONTROLLABLE
        assert await controller.health() == {"status": "ok"}
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_automatic_recovery_respects_supporting_gpu_reservations(tmp_path):
    async def scenario():
        controller = app(tmp_path)
        await controller._main_model_manager.initialize()
        controller._VRAM_FRACTION = {"embedding-vllm": 0.85}
        class Executor:
            async def status(self, service):
                return "running"
        controller._executor = lambda: Executor()
        for now in (0, 10, 50):
            await controller._adaptive_control.step(now=now)
        assert controller._main_model_manager.snapshot()["active_profile"]["id"] == CPU
        assert controller._state_store.read()["runtime_selection"]["reason_code"] == "GPU_BUDGET_BLOCKED"
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize(("mode", "profile"), [("cpu", GPU), ("automatic", GPU), ("gpu", CPU), ([], CPU)])
def test_invalid_policy_does_not_change_runtime(tmp_path, mode, profile):
    async def scenario():
        controller = app(tmp_path)
        before = controller._state_store.read()
        with pytest.raises(HTTPException) as error:
            await controller.switch_main_model({"profile": profile, "execution_policy": mode}, authorization=None)
        assert error.value.status_code == 422
        assert controller._state_store.read() == before
    asyncio.run(scenario())


def test_supporting_transition_cannot_race_pending_main_switch(tmp_path):
    async def scenario():
        controller = app(tmp_path)
        await controller._main_model_manager.initialize()
        controller._main_model_manager.request_switch(CPU, confirm_unverified=True)
        with pytest.raises(HTTPException) as error:
            await controller._runtime_transition_plan(next(iter(controller.CONTROLLABLE)), "active", force=True)
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "MODEL_SWITCH_IN_PROGRESS"
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_failed_cpu_preparation_keeps_gpu_policy_and_serving(tmp_path):
    async def scenario():
        backend = Backend(observed=GPU)
        controller = app(tmp_path, mode="gpu", backend=backend)
        # 실제로 검증한 GPU 상태를 만든 뒤 CPU Artifact 실패를 주입한다.
        controller._main_model_manager.boot_profile = GPU
        await controller._main_model_manager.initialize()
        backend.fail_prepare = True
        response = await controller.switch_main_model({"profile": CPU, "execution_policy": "cpu", "confirm_unverified": True}, authorization=None)
        result = await controller._main_model_manager.wait_for_operation(json.loads(response.body)["operation_id"])
        assert result["status"] == "failed"
        state = controller._state_store.read()
        assert state["runtime_selection"]["mode"] == "gpu" and state["gate"] == "open"
        assert state["active_profile"] == GPU
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_request_id_cannot_be_reused_for_a_different_policy(tmp_path):
    async def scenario():
        controller = app(tmp_path)
        await controller._main_model_manager.initialize()
        await switch(controller, "cpu", request_id="policy-request")
        state = controller._state_store.read()
        with pytest.raises(HTTPException) as error:
            await controller.switch_main_model({"profile": CPU, "execution_policy": "automatic", "confirm_unverified": True, "request_id": "policy-request"}, authorization=None)
        assert error.value.status_code == 409
        assert controller._state_store.read() == state
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_cpu_policy_rollback_cannot_bypass_automatic_gpu_pressure_validation(tmp_path, monkeypatch):
    from ai_model_serving.main_model.docker_backend import DockerMainModelBackend
    from tests.unit.test_adaptive_runtime import BUSY

    async def scenario():
        async def reader():
            return BUSY
        controller = create_runtime_controller_app(environment={
            "APP_CONFIG_ROOT": str(ROOT), "MAIN_MODEL_STATE_PATH": str(tmp_path / "state.json"),
            "COMPOSE_PROJECT": "managed-test", "VLLM_IMAGE": _SHARED_IMAGE,
            "MAIN_MODEL_BOOT_PROFILE": CPU, "MAIN_MODEL_EXECUTION_POLICY": "automatic",
        }, resource_reader=reader).state.controller
        engine = controller._main_model_manager.backend
        assignment, _ = engine.gpu_policies.choose(FREE)
        engine.bind_gpu(assignment)
        controller._state_store.update(lambda state: state.update(last_operation={
            "status": "pending", "requested_profile": CPU, "execution_policy": "cpu",
        }))
        async def validated(*args):
            pass
        async def observed(*args):
            return {"gpu_device_uuid": FREE.gpus[0].uuid}
        monkeypatch.setattr(DockerMainModelBackend, "validate", validated)
        monkeypatch.setattr(engine, "observe_runtime", observed)
        with pytest.raises(RuntimeError, match="GPU_REVALIDATION_RESOURCE_UNSAFE"):
            await engine.validate(controller._catalog, assignment.profile)
    asyncio.run(scenario())
