"""GPU 부족·시작 실패의 CPU 복구와 수동 GPU 복귀를 보호한다."""

import asyncio
from dataclasses import replace

import pytest

from ai_model_serving.main_model.execution_policy import resolve_execution_policy
from ai_model_serving.main_model.gpu_compatibility import driver_compatibility_error
from tests.unit.test_managed_execution_policy import app, switch, CPU, GPU
from tests.unit.test_adaptive_runtime import Backend, FREE, BUSY


@pytest.mark.parametrize(("state", "env", "expected"), [
    ({}, {}, "fallback"),
    ({}, {"MAIN_MODEL_BOOT_PROFILE": GPU}, "fallback"),
    ({"active_profile": CPU}, {"MAIN_MODEL_BOOT_PROFILE": GPU}, "cpu"),
    ({}, {"MAIN_MODEL_EXECUTION_POLICY": "gpu"}, "gpu"),
    ({"runtime_selection": {"mode": "cpu"}}, {"MAIN_MODEL_EXECUTION_POLICY": "fallback"}, "cpu"),
    ({"runtime_selection": {"mode": "gpu"}}, {}, "gpu"),
    ({"active_profile": CPU}, {"MAIN_MODEL_BOOT_PROFILE": GPU, "MAIN_MODEL_PROFILE_LOCKED": "true"}, "gpu"),
])
def test_policy_priority_preserves_explicit_choices(state, env, expected):
    assert resolve_execution_policy(state, env) == expected


def test_locked_model_cannot_enable_automatic_cpu_substitution():
    with pytest.raises(ValueError, match="MAIN_MODEL_PROFILE_LOCKED"):
        resolve_execution_policy({}, {"MAIN_MODEL_PROFILE_LOCKED": "true", "MAIN_MODEL_EXECUTION_POLICY": "fallback"})


@pytest.mark.parametrize(("variant", "driver", "error"), [
    ("cu130", "570.195.03", "GPU_DRIVER_INCOMPATIBLE"),
    ("cu130", "580.178.04", None),
    ("cu129", "570.195.03", None),
    ("cu129", "525.60.12", "GPU_DRIVER_INCOMPATIBLE"),
    ("cu129", None, "GPU_DRIVER_COMPATIBILITY_UNKNOWN"),
    ("", "580.178.04", "GPU_DRIVER_COMPATIBILITY_UNKNOWN"),
])
def test_driver_guard_checks_minimum_without_claiming_canary(variant, driver, error):
    image = {"Config": {"Labels": {"ai_model_serving.cuda_variant": variant}}}
    assert driver_compatibility_error(image, driver) == error


def test_legacy_image_uses_cuda_metadata_instead_of_tag():
    image = {"Config": {"Env": ["CUDA_VERSION=13.0.0"]}}
    assert driver_compatibility_error(image, "570.195.03") == "GPU_DRIVER_INCOMPATIBLE"


def test_driver_rejection_precedes_model_download_and_runtime_replacement(monkeypatch, tmp_path):
    from ai_model_serving.main_model.adaptive_backend import AdaptiveDockerBackend
    from ai_model_serving.main_model.adaptive_catalog import load_adaptive_catalog
    from ai_model_serving.main_model.docker_backend import DockerMainModelBackend
    from tests.unit.test_managed_execution_policy import ROOT
    from tests.support.main_model import _SHARED_IMAGE

    async def scenario():
        catalog, policy, resolver = load_adaptive_catalog(ROOT, {"VLLM_IMAGE": _SHARED_IMAGE})
        observed = replace(FREE, gpus=(replace(FREE.gpus[0], driver_version="570.195.03"),))
        assignment, reason = resolver.choose(observed)
        assert reason is None
        async def reader():
            return observed
        async def image(_):
            return {"Config": {"Labels": {"ai_model_serving.cuda_variant": "cu130"}}}
        async def forbidden(*args):
            pytest.fail("호환 불가 이미지의 다운로드·교체가 실행됨")
        backend = AdaptiveDockerBackend("/not-used", "owned", gateway_url="http://gateway:9400",
            config_root=ROOT, cpu_cache_dir=tmp_path, resource_reader=reader,
            selection_policy=policy, gpu_policies=resolver)
        backend.bind_gpu(assignment)
        monkeypatch.setattr(backend, "_inspect_image", image)
        monkeypatch.setattr(DockerMainModelBackend, "prepare", forbidden)
        monkeypatch.setattr(DockerMainModelBackend, "replace", forbidden)
        for method in (backend.prepare, backend.replace):
            with pytest.raises(RuntimeError, match="GPU_DRIVER_INCOMPATIBLE"):
                await method(catalog, assignment.profile)
    asyncio.run(scenario())


def test_fixed_gpu_preflight_reports_driver_failure_without_starting_container(monkeypatch, capsys):
    import json
    import subprocess
    from scripts.compose import preflight_compose as preflight

    calls = []
    def run(command, **kwargs):
        calls.append(command)
        output = json.dumps({"Config": {"Env": ["CUDA_VERSION=13.0.0"]}}) if command[0] == "docker" else "570.195.03\n"
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(preflight, "_run_status", run)
    assert not preflight._check_main_gpu_driver({"services": {"main-llm-vllm": {"image": "sha256:" + "a" * 64}}})
    assert "GPU_DRIVER_INCOMPATIBLE" in capsys.readouterr().err
    assert all("start" not in command and "run" not in command for command in calls)


@pytest.mark.parametrize("fresh", [False, True])
def test_default_cli_uses_cpu_first_and_preserves_core_on_cpu_preparation_failure(tmp_path, monkeypatch, fresh):
    from scripts import platform_cli as cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ENV_PATH", tmp_path / ".env")
    def setup(*args):
        cli.ENV_PATH.write_text("BUILD_PROFILE=compose\n")
        return True
    monkeypatch.setattr(cli, "setup_target", setup)
    monkeypatch.setattr(cli, "_assert_host_ports_available", lambda values: None)
    if not fresh:
        cli.ENV_PATH.write_text("BUILD_PROFILE=compose\n")
    calls = []
    monkeypatch.setattr(cli, "ensure_target_artifacts", lambda *a, **k: calls.append("image"))
    monkeypatch.setattr(cli, "start_core", lambda *a: calls.append("core"))
    def fail(*args):
        calls.append("cpu")
        raise RuntimeError("CPU_RAM_ADMISSION_FAILED")
    monkeypatch.setattr(cli, "up_managed_cpu_first", fail)
    monkeypatch.setattr(cli, "prepare_target", lambda *a: pytest.fail("GPU 기동 경로로 진입함"))
    target = cli.load_deployment_target(cli.TARGETS_PATH, "linux-nvidia-dynamic")
    with pytest.raises(RuntimeError, match="CPU_RAM_ADMISSION_FAILED"):
        cli.reconcile_up_target(target, main_profile=None, main_base_url=None, access_profile=None, confirm_access=False)
    assert calls == ["image", "core", "cpu"]
    assert cli.managed_execution_policy(cli._env_values()) == "fallback"


def test_cpu_template_never_switches_to_gpu_boot_seed_before_admission(tmp_path):
    async def scenario():
        backend = Backend(observed=CPU)
        controller = app(tmp_path, "fallback", backend=backend)
        controller._main_model_manager.boot_profile = "gemma4-12b-unified-fp8"
        await controller._run_initialize()
        state = controller._state_store.read()
        assert state["gate"] == "open" and state["active_profile"] == CPU
        assert backend.prepared == [] and backend.replaced == []
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_busy_ada_stays_cpu_after_resources_recover_and_controller_restarts(tmp_path):
    async def scenario():
        observations = [replace(FREE, gpus=(replace(FREE.gpus[0], total_mib=49140,
            free_mib=4064, name="NVIDIA RTX 6000 Ada Generation", driver_version="570.195.03"),))]
        controller = app(tmp_path, "fallback")
        async def reader():
            return observations[0]
        controller._adaptive_control.resources = reader
        await controller._run_initialize()
        await controller._adaptive_control.step(now=0)
        assert controller._state_store.read()["runtime_selection"]["reason_code"] == "GPU_MEMORY_INSUFFICIENT"
        observations[0] = FREE
        for now in (5, 35, 60, 120):
            await controller._adaptive_control.step(now=now)
        assert controller._state_store.read()["active_profile"] == CPU
        restarted = app(tmp_path, "automatic")
        await restarted._run_initialize()
        for now in (200, 240, 280):
            await restarted._adaptive_control.step(now=now)
        state = restarted._state_store.read()
        assert state["active_profile"] == CPU and state["gate"] == "open"
        assert state["runtime_selection"]["mode"] == "fallback"
        assert state["runtime_selection"]["reason_code"] == "CPU_FALLBACK_ACTIVE"
        # 수동으로 검토·적용한 같은 정책은 GPU 사용을 다시 한 번 확인한다.
        await switch(restarted, "fallback")
        assert restarted._main_model_manager.backend.replaced == []
        for now in (300, 340, 380):
            await restarted._adaptive_control.step(now=now)
        operation = restarted._state_store.read()["last_operation"]
        await restarted._main_model_manager.wait_for_operation(operation["id"])
        assert restarted._state_store.read()["active_profile"] == GPU
        await controller._main_model_manager.aclose()
        await restarted._main_model_manager.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("error", ["GPU_DRIVER_INCOMPATIBLE", "GPU_MEMORY_ADMISSION_BLOCKED"])
def test_gpu_preparation_failure_keeps_cpu_gate_open_without_automatic_retry(tmp_path, error):
    class FailingGpu(Backend):
        async def prepare(self, catalog, profile):
            await super().prepare(catalog, profile)
            if profile.runtime_backend != "llama-cpp":
                raise RuntimeError(error)

    async def scenario():
        backend = FailingGpu(observed=CPU)
        controller = app(tmp_path, "fallback", backend=backend)
        await controller._run_initialize()
        for now in (0, 35, 70):
            await controller._adaptive_control.step(now=now)
        manager = controller._main_model_manager
        operation = controller._state_store.read()["last_operation"]
        result = await manager.wait_for_operation(operation["id"])
        assert result["status"] == "failed" and result["error"] == error
        for now in (100, 200, 300):
            await controller._adaptive_control.step(now=now)
        state = controller._state_store.read()
        assert state["gate"] == "open" and state["active_profile"] == CPU
        assert backend.replaced == []
        assert backend.prepared.count(GPU) == 1
        assert await controller.health() == {"status": "ok"}
        await manager.aclose()
    asyncio.run(scenario())


def test_manual_gpu_retry_cannot_reopen_cpu_with_a_failed_canary(tmp_path):
    async def scenario():
        backend = Backend(observed=CPU)
        controller = app(tmp_path, "fallback", backend=backend)
        await controller._run_initialize()
        backend.fail_profile = CPU
        response = await controller.switch_main_model({"profile": CPU, "execution_policy": "fallback", "confirm_unverified": True}, authorization=None)
        import json
        result = await controller._main_model_manager.wait_for_operation(json.loads(response.body)["operation_id"])
        assert result["status"] == "failed"
        assert controller._state_store.read()["gate"] == "closed"
        assert backend.replaced == []
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


def test_gpu_canary_failure_rolls_back_to_cpu_once(tmp_path):
    async def scenario():
        backend = Backend(observed=CPU, fail_profile=GPU)
        controller = app(tmp_path, "fallback", backend=backend)
        await controller._run_initialize()
        for now in (0, 35, 70):
            await controller._adaptive_control.step(now=now)
        manager = controller._main_model_manager
        operation = controller._state_store.read()["last_operation"]
        assert (await manager.wait_for_operation(operation["id"]))["status"] == "failed"
        for now in (100, 200, 300):
            await controller._adaptive_control.step(now=now)
        assert backend.replaced == [GPU, CPU]
        assert controller._state_store.read()["gate"] == "open"
        await manager.aclose()
    asyncio.run(scenario())


def test_running_gpu_failure_recovers_cpu_and_preserves_manual_return(tmp_path):
    async def scenario():
        backend = Backend(observed=GPU)
        controller = app(tmp_path, "fallback", backend=backend)
        manager = controller._main_model_manager
        manager.boot_profile = GPU
        await controller._run_initialize()
        await controller._adaptive_control.step(now=0)
        backend.observed = None
        for now in (5, 10):
            await controller._adaptive_control.step(now=now)
        result = await manager.wait_for_operation(controller._state_store.read()["last_operation"]["id"])
        assert result["status"] == "completed"
        for now in (100, 200, 300):
            await controller._adaptive_control.step(now=now)
        state = controller._state_store.read()
        assert state["active_profile"] == CPU and state["gate"] == "open"
        assert backend.replaced == [CPU]
        await manager.aclose()
    asyncio.run(scenario())


def test_explicit_gpu_policy_never_silently_changes_to_cpu(tmp_path):
    async def scenario():
        backend = Backend(observed=GPU, fail_profile=GPU)
        controller = app(tmp_path, "gpu", backend=backend, resources=BUSY)
        controller._main_model_manager.boot_profile = GPU
        await controller._run_initialize()
        for now in (0, 60, 120):
            await controller._adaptive_control.step(now=now)
        assert controller._state_store.read()["gate"] == "closed"
        assert backend.replaced == []
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("canary_failure", [False, True])
def test_failed_gpu_at_controller_boot_cannot_automatically_return_after_cpu_recovery(tmp_path, canary_failure):
    async def scenario():
        backend = Backend(observed=GPU if canary_failure else None, fail_profile=GPU if canary_failure else None)
        controller = app(tmp_path, "fallback", backend=backend)
        controller._state_store.update(lambda state: state.update(active_profile=GPU))
        manager = controller._main_model_manager
        manager.boot_profile = GPU
        await controller._run_initialize()
        operation = controller._state_store.read()["last_operation"]
        assert (await manager.wait_for_operation(operation["id"]))["status"] == "completed"
        for now in (0, 40, 80, 120, 160):
            await controller._adaptive_control.step(now=now)
        state = controller._state_store.read()
        assert state["active_profile"] == CPU and state["gate"] == "open"
        assert backend.replaced == [CPU]
        assert state["runtime_selection"]["gpu_attempted"] is True
        await manager.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["automatic", "fallback"])
def test_gpu_canary_failure_after_external_restart_recovers_cpu(tmp_path, mode):
    async def scenario():
        backend = Backend(observed=GPU)
        controller = app(tmp_path, mode, backend=backend)
        manager = controller._main_model_manager
        manager.boot_profile = GPU
        await controller._run_initialize()
        await controller._adaptive_control.step(now=0)
        backend.started_at = "restarted-instance"
        backend.fail_profile = GPU
        for now in (5, 10, 15, 20, 25):
            await controller._adaptive_control.step(now=now)
            operation = controller._state_store.read().get("last_operation")
            if operation:
                await manager.wait_for_operation(operation["id"])
        assert controller._state_store.read()["active_profile"] == CPU
        assert controller._state_store.read()["gate"] == "open"
        assert backend.replaced == [CPU]
        await manager.aclose()
    asyncio.run(scenario())


def test_published_policy_contract_matches_shared_resolution():
    import json
    from tests.unit.test_managed_execution_policy import ROOT
    from ai_model_serving.main_model.execution_policy import EXECUTION_POLICIES
    for name, key in (("main_model_switch_request", "execution_policy"), ("main_model_status_response", "runtime_selection")):
        schema = json.loads((ROOT / "specs/schemas" / (name + ".schema.json")).read_text())
        policy = schema["properties"][key]
        if key == "runtime_selection":
            policy = policy["properties"]["mode"]
        assert policy["enum"] == list(EXECUTION_POLICIES)


def test_stopped_intent_does_not_trigger_cpu_or_gpu_start(tmp_path):
    async def scenario():
        backend = Backend(observed=GPU)
        controller = app(tmp_path, "fallback", backend=backend)
        controller._state_store.update(lambda state: state.update(runtime_state="stopped"))
        await controller._run_initialize()
        for now in (0, 60, 120):
            await controller._adaptive_control.step(now=now)
        assert controller._state_store.read()["gate"] == "closed"
        assert backend.replaced == [] and backend.started == 0
        await controller._main_model_manager.aclose()
    asyncio.run(scenario())
