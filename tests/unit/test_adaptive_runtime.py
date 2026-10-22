"""자동 선택도 Main 전환의 요청 보호·검증·운영자 의도를 따른다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_model_serving.apps.adaptive_controller import create_adaptive_controller_app
from ai_model_serving.host_resource_probe import GpuMemory, HostResourceSnapshot
from ai_model_serving.main_model.adaptive import AdaptiveMainModelControl
from ai_model_serving.main_model.adaptive_backend import fitting_gpu
from ai_model_serving.main_model.adaptive_catalog import load_adaptive_catalog
from ai_model_serving.main_model.control import MainModelManager
from ai_model_serving.main_model.state import MainModelStateStore
from tests.support.main_model import FakeBackend, _SHARED_IMAGE

ROOT = Path(__file__).resolve().parents[2]
CPU = "cpu-gguf-text"
GPU = "gemma4-e4b-it"
UUID = "GPU-00000000-0000-0000-0000-000000000001"
FREE = HostResourceSnapshot(
    (
        GpuMemory(
            0,
            24564,
            23000,
            "NVIDIA GeForce RTX 4090",
            UUID,
            "00000000:01:00.0",
            "8.9",
            "580.178.04",
        ),
    ),
    32000,
    None,
)
BUSY = replace(FREE, gpus=(replace(FREE.gpus[0], free_mib=300),))
UNKNOWN = HostResourceSnapshot((), 32000, "GPU_MEMORY_OBSERVATION_FAILED")


class Backend(FakeBackend):
    async def observe_runtime(self, catalog):
        return {
            "status": "ready" if self.observed else "not_ready",
            "profile_id": self.observed,
            "gpu_device_uuid": UUID,
            "container_state": "running" if self.observed else "not_found",
            "health": "healthy" if self.observed else None,
        }


def fixture(tmp_path, *, snapshot=FREE, **backend_options):
    catalog, policy, gpu_policies = load_adaptive_catalog(
        ROOT, {"VLLM_IMAGE": _SHARED_IMAGE}
    )
    assert gpu_policies.error is None
    backend = Backend(**backend_options)
    store = MainModelStateStore(tmp_path / "main.json", CPU)
    manager = MainModelManager(catalog, store, backend)
    observations = [snapshot]

    async def resources():
        return observations[0]

    control = AdaptiveMainModelControl(
        manager, policy, resources, gpu_policies=gpu_policies
    )
    return manager, control, backend, observations


async def settle(manager):
    operation = manager.state_store.read()["last_operation"]
    return await manager.wait_for_operation(operation["id"])


def test_cpu_bootstrap_then_stable_gpu_and_pressure_fallback(tmp_path):
    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        await control.step(now=0)
        assert (await settle(manager))["status"] == "completed"
        assert manager.snapshot()["active_profile"]["id"] == CPU
        await control.step(now=5)
        await control.step(now=10)
        await control.step(now=15)
        assert backend.replaced == [CPU]
        await control.step(now=40)
        assert (await settle(manager))["status"] == "completed"
        assert manager.snapshot()["active_profile"]["id"] == GPU
        observations[0] = BUSY
        await control.step(now=45)
        assert manager.snapshot()["active_profile"]["id"] == GPU
        await control.step(now=50)
        assert (await settle(manager))["status"] == "completed"
        assert backend.replaced == [CPU, GPU, CPU]
        assert backend.drain_calls == 3
        assert manager.snapshot()["gate"] == "open"
        await manager.aclose()

    asyncio.run(scenario())


def test_gpu_canary_failure_rolls_back_and_honors_durable_backoff(tmp_path):
    async def scenario():
        manager, control, backend, _ = fixture(tmp_path, fail_profile=GPU)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40):
            await control.step(now=now)
        assert (await settle(manager))["status"] == "failed"
        assert backend.replaced == [CPU, GPU, CPU]
        assert manager.snapshot()["gate"] == "open"
        await control.step(now=45)
        deadline = manager.state_store.read()["runtime_selection"]["gpu_retry_at"]
        restarted = AdaptiveMainModelControl(
            manager,
            control.policy,
            control.resources,
            gpu_policies=control.gpu_policies,
        )
        for now in (60, 90, 100):
            await restarted.step(now=now)
        assert backend.replaced == [CPU, GPU, CPU]
        assert (
            manager.state_store.read()["runtime_selection"]["gpu_retry_at"] == deadline
        )
        assert (
            manager.state_store.read()["runtime_selection"]["reason_code"]
            == "GPU_FAILURE_BACKOFF"
        )
        await manager.aclose()

    asyncio.run(scenario())


def test_unknown_gpu_never_promotes_and_operator_stop_survives_restart(tmp_path):
    async def scenario():
        manager, control, backend, observations = fixture(tmp_path, snapshot=UNKNOWN)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40):
            await control.step(now=now)
        assert backend.replaced == [CPU]
        await manager.stop_main(strict_drain=True)
        observations[0] = FREE
        reloaded = MainModelManager(manager.catalog, manager.state_store, backend)
        restarted = AdaptiveMainModelControl(
            reloaded,
            control.policy,
            control.resources,
            gpu_policies=control.gpu_policies,
        )
        await reloaded.initialize()
        await restarted.step(now=100)
        assert backend.replaced == [CPU]
        assert reloaded.snapshot()["gate"] == "closed"
        assert (
            manager.state_store.read()["runtime_selection"]["reason_code"]
            == "OPERATOR_STOPPED"
        )
        await manager.aclose()

    asyncio.run(scenario())


def test_drain_failure_keeps_verified_runtime_and_strict_stop_does_not_kill(tmp_path):
    async def scenario():
        manager, control, backend, _ = fixture(tmp_path)
        await control.step(now=0)
        await settle(manager)
        backend.fail_drain = True
        for now in (5, 10, 40):
            await control.step(now=now)
        assert (await settle(manager))["status"] == "failed"
        assert backend.replaced == [CPU]
        assert manager.snapshot()["gate"] == "open"
        with pytest.raises(RuntimeError, match="drain timed out"):
            await manager.stop_main(strict_drain=True)
        assert backend.stopped == 0
        assert manager.snapshot()["gate"] == "open"
        await manager.aclose()

    asyncio.run(scenario())


def test_gpu_admission_is_per_device_and_rejects_unknown(tmp_path):
    manager, control, _, _ = fixture(tmp_path)
    profile = manager.catalog.profiles[GPU]
    split = HostResourceSnapshot(
        (
            replace(FREE.gpus[0], free_mib=12000),
            replace(
                FREE.gpus[0],
                index=1,
                free_mib=12000,
                uuid="GPU-00000000-0000-0000-0000-000000000002",
            ),
        ),
        32000,
        None,
    )
    assert fitting_gpu(split, profile, control.policy) is None
    assert (
        fitting_gpu(
            replace(FREE, gpu_observation_error="unavailable"), profile, control.policy
        )
        is None
    )
    assert fitting_gpu(FREE, profile, control.policy).index == 0


def test_adaptive_controller_requires_internal_auth_and_locks_manual_profiles(tmp_path):
    app = create_adaptive_controller_app(
        environment={
            "APP_CONFIG_ROOT": str(ROOT),
            "MAIN_MODEL_STATE_PATH": str(tmp_path / "main.json"),
            "COMPOSE_PROJECT": "test-adaptive",
            "VLLM_IMAGE": _SHARED_IMAGE,
            "INTERNAL_SERVICE_AUTH_REQUIRED": "true",
            "INTERNAL_SERVICE_TOKEN": "test-private-observer-token",
        },
        backend=Backend(),
    )
    # lifespan 없이 권한 계약만 검증한다. 자동 루프는 위 상태 전환 테스트에서 실행한다.
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/main-model").status_code == 401
    headers = {"Authorization": "Bearer test-private-observer-token"}
    value = client.get("/main-model", params={"observed": "false"}, headers=headers)
    assert value.status_code == 200
    assert value.json()["profile_locked"] is True
    assert (
        client.post(
            "/main-model/switch", headers=headers, json={"profile": GPU}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/runtime-transitions/other-project/plan",
            headers=headers,
            json={"desired_state": "active"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("target_id", ["linux-cpu-managed", "linux-nvidia-dynamic"])
def test_model_preparation_failure_keeps_core_started(tmp_path, monkeypatch, target_id):
    from scripts import platform_cli as cli

    calls = []
    target = cli.load_deployment_target(cli.TARGETS_PATH, target_id)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "ENV_PATH", tmp_path / ".env")
    cli.ENV_PATH.write_text("BUILD_PROFILE=compose\nMAIN_MODEL_EXECUTION_POLICY=gpu\n")
    monkeypatch.setattr(cli, "setup_target", lambda *args: True)
    monkeypatch.setattr(
        cli, "ensure_target_artifacts", lambda *args, **kwargs: calls.append("image")
    )
    monkeypatch.setattr(cli, "start_core", lambda *args: calls.append("core"))

    def fail(*args):
        calls.append("model")
        raise RuntimeError("RAM admission failed")

    monkeypatch.setattr(cli, "prepare_target", fail)
    monkeypatch.setattr(cli, "up_target", lambda *args: calls.append("full"))
    with pytest.raises(RuntimeError, match="RAM admission"):
        cli.reconcile_up_target(
            target,
            main_profile=None,
            main_base_url=None,
            access_profile=None,
            confirm_access=False,
        )
    assert calls == ["image", "core", "image", "model"]


def test_stale_resource_observation_cannot_admit_gpu(monkeypatch):
    import time
    import httpx
    import ai_model_serving.main_model.adaptive_backend as module

    reader = module.AdaptiveResourceReader(
        "http://resource-observer:8081", "private-token"
    )
    payload = {
        "observed_at": time.time() - 60,
        "gpus": [{"index": 0, "total_mib": 24564, "free_mib": 24564}],
        "ram_available_mib": 32000,
        "gpu_observation_error": None,
    }
    original = httpx.AsyncClient

    def response(request):
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    observed = asyncio.run(reader())
    assert observed.gpus == ()
    assert observed.gpu_observation_error == "GPU_MEMORY_OBSERVATION_FAILED"


def test_missing_gpu_artifact_after_restart_recovers_through_cpu(tmp_path):
    store = MainModelStateStore(tmp_path / "main.json", CPU)
    store.update(lambda state: state.update(active_profile=GPU, gate="open"))
    app = create_adaptive_controller_app(
        environment={
            "APP_CONFIG_ROOT": str(ROOT),
            "MAIN_MODEL_STATE_PATH": str(store.path),
            "COMPOSE_PROJECT": "test-adaptive",
            "VLLM_IMAGE": "missing-mutable:tag",
        },
        backend=Backend(),
    )
    manager = app.state.main_model_manager
    assert manager.boot_profile == CPU
    assert manager.snapshot()["gate"] == "closed"
    assert manager.snapshot()["active_profile"] is None


def test_gateway_projects_verified_backend_policy_and_closes_readiness(
    monkeypatch, tmp_path
):
    """별칭이 같아도 CPU/GPU 정책과 Gate를 실제 활성 Profile에 맞춰 공개한다."""
    from ai_model_serving.apps.gateway import create_gateway_app
    from ai_model_serving.settings import load_settings
    from ai_model_serving.openapi_contracts import load_contract_schema
    from jsonschema import Draft202012Validator
    from tests.unit.gateway.helpers import FakeGatewayClients

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-adaptive")
    config = load_settings(root=ROOT, env_file=tmp_path / "no-env")
    catalog, _, _ = load_adaptive_catalog(ROOT, {"VLLM_IMAGE": _SHARED_IMAGE})
    snapshot = {
        "active_profile": catalog.profiles[CPU].public_view(),
        "gate": "open",
        "engine_policy": catalog.profiles[CPU].engine_policy(),
    }

    class Controller:
        async def main_model(self, observed=True):
            return snapshot

    clients = FakeGatewayClients()
    clients.runtime_controller = Controller()
    clients.main_llm.get_response = {"data": [{"id": "local-main", "meta": {}}]}
    client = TestClient(create_gateway_app(config, clients))
    for profile_id in (CPU, GPU):
        profile = catalog.profiles[profile_id]
        snapshot.update(
            active_profile=profile.public_view(), engine_policy=profile.engine_policy()
        )
        item = client.get("/v1/models").json()["data"][0]
        assert item["backend"] == profile.runtime_backend
        assert item["input_modalities"] == profile.capabilities["deployed_input"]
        assert (
            item["request_parameters"]["max_tokens"]["max"]
            == profile.gateway_policy["max_output_tokens"]
        )
        envelope = client.get("/admin/serving-envelope")
        assert envelope.status_code == 200
        Draft202012Validator(
            load_contract_schema("serving_envelope_response.schema.json")
        ).validate(envelope.json())
        assert client.get("/ready").status_code == 200
    snapshot["gate"] = "closed"
    assert client.get("/v1/models").json()["data"] == []
    assert client.get("/ready").status_code == 503


def test_make_up_keeps_existing_main_and_explicit_stop(monkeypatch, capsys):
    from types import SimpleNamespace
    from scripts import platform_cli as cli

    target = cli.load_deployment_target(cli.TARGETS_PATH, "linux-adaptive")
    calls = []
    monkeypatch.setattr(cli, "_env_values", lambda: {})
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="existing-main-id\n"),
    )
    monkeypatch.setattr(
        cli, "_static_compose", lambda target, label, *args: calls.append(args)
    )
    monkeypatch.setattr(cli, "read_host_resource_snapshot", lambda: UNKNOWN)
    monkeypatch.setattr(
        cli,
        "_gateway_json",
        lambda *args, **kwargs: (200, {"runtime_state": "stopped"}),
    )
    monkeypatch.setattr(cli, "_print_next_steps", lambda *args: None)
    cli.up_adaptive_target(target)
    assert calls == [("up", "-d", "--no-deps", "runtime-controller")]
    assert "Main is explicitly stopped" in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure", ["CPU RAM admission blocked", "CPU artifact checksum mismatch"]
)
def test_failed_cpu_preparation_keeps_gpu_closed_until_pressure_recovers(
    tmp_path, failure
):
    """압력 중 CPU 준비 실패는 GPU를 보존하고, 압력 해소 뒤 같은 인스턴스만 재검증한다."""

    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40):
            await control.step(now=now)
        await settle(manager)
        before = len(backend.validate_calls)
        original_started_at = backend.started_at

        async def unavailable_cpu(catalog, profile):
            assert profile.profile_id == CPU
            raise RuntimeError(failure)

        backend.prepare = unavailable_cpu
        observations[0] = BUSY
        await control.step(now=45)
        assert manager.snapshot()["gate"] == "closed"
        await control.step(now=50)
        op = await settle(manager)
        assert op["status"] == "failed" and op["stage"] == "preparing"
        assert failure in op["error"]
        assert backend.replaced == [CPU, GPU]
        for now in (55, 60):
            await control.step(now=now)
            assert manager.snapshot()["gate"] == "closed"
        assert len(backend.validate_calls) == before
        assert (
            manager.state_store.read()["runtime_selection"]["reason_code"]
            == "CPU_FALLBACK_PREPARATION_FAILED"
        )
        observations[0] = FREE
        for now in (65, 70):
            await control.step(now=now)
            assert manager.snapshot()["gate"] == "closed"
        await control.step(now=75)
        assert manager.snapshot()["gate"] == "open"
        assert backend.validate_calls[before:] == [GPU]
        assert backend.started_at == original_started_at
        assert backend.replaced == [CPU, GPU]
        assert manager.state_store.read()["runtime_selection"]["cpu_retry_at"] > 75
        await manager.aclose()

    asyncio.run(scenario())


def test_runtime_failure_cannot_reopen_gate_from_memory_recovery_alone(tmp_path):
    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40):
            await control.step(now=now)
        await settle(manager)
        baseline = len(backend.validate_calls)
        backend.observed = None
        backend.fail_prepare = True
        for now in (45, 50):
            await control.step(now=now)
        assert (await settle(manager))["stage"] == "preparing"
        for now in (55, 60, 65):
            await control.step(now=now)
            assert manager.snapshot()["gate"] == "closed"
        selection = manager.state_store.read()["runtime_selection"]
        assert selection["gpu_condition"] == "GPU_RUNTIME_UNHEALTHY"
        assert selection["reason_code"] == "CPU_FALLBACK_PREPARATION_FAILED"
        assert backend.validate_calls[baseline:] == []
        assert backend.replaced == [CPU, GPU]
        await manager.aclose()

    asyncio.run(scenario())


def test_cleared_pressure_still_requires_successful_gpu_canary(tmp_path):
    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40):
            await control.step(now=now)
        await settle(manager)
        backend.fail_prepare = True
        observations[0] = BUSY
        for now in (45, 50):
            await control.step(now=now)
        await settle(manager)
        await control.step(now=55)
        observations[0] = FREE
        backend.fail_profile = GPU
        baseline = len(backend.validate_calls)
        for now in (60, 65, 70):
            await control.step(now=now)
        assert backend.validate_calls[baseline:] == [GPU]
        assert manager.snapshot()["gate"] == "closed"
        assert (
            manager.state_store.read()["runtime_selection"]["reason_code"]
            == "GPU_REVALIDATION_FAILED"
        )
        assert backend.replaced == [CPU, GPU]
        await manager.aclose()

    asyncio.run(scenario())


def test_gpu_recovery_samples_do_not_combine_different_devices(tmp_path):
    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        await control.step(now=0)
        await settle(manager)
        for now in (5, 10, 40, 45):
            observations[0] = (
                FREE
                if now in (5, 40)
                else replace(
                    FREE,
                    gpus=(
                        replace(
                            FREE.gpus[0],
                            uuid="GPU-00000000-0000-0000-0000-000000000002",
                        ),
                    ),
                )
            )
            await control.step(now=now)
        assert backend.replaced == [CPU]
        assert manager.state_store.read()["runtime_selection"]["healthy_samples"] == 1
        await manager.aclose()

    asyncio.run(scenario())


def test_adaptive_status_schema_covers_candidate_assignment_and_failed_fallback(
    tmp_path,
):
    from jsonschema import Draft202012Validator
    from ai_model_serving.openapi_contracts import load_contract_schema

    async def scenario():
        manager, control, backend, observations = fixture(tmp_path)
        validator = Draft202012Validator(
            load_contract_schema("main_model_status_response.schema.json")
        )

        async def check():
            status = await manager.observed_snapshot()
            status["runtime_selection"] = manager.state_store.read()[
                "runtime_selection"
            ]
            validator.validate(status)

        await control.step(now=0)
        await settle(manager)
        await control.step(now=5)
        await check()
        for now in (10, 40):
            await control.step(now=now)
        await settle(manager)
        await check()
        backend.fail_prepare = True
        observations[0] = BUSY
        for now in (45, 50):
            await control.step(now=now)
        await settle(manager)
        await control.step(now=55)
        await check()
        await manager.aclose()

    asyncio.run(scenario())
