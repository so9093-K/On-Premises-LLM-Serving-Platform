"""48GB 준비는 합성 장치 관측으로 검증하며 실기기 Qualification으로 주장하지 않는다."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from ai_model_serving.host_resource_probe import GpuMemory, HostResourceSnapshot
from ai_model_serving.main_model.adaptive_catalog import load_adaptive_catalog
from ai_model_serving.main_model.adaptive_backend import AdaptiveDockerBackend
from tests.support.main_model import _SHARED_IMAGE

ROOT = Path(__file__).resolve().parents[2]
UUID = "GPU-00000000-0000-0000-0000-000000000001"
UUID2 = "GPU-00000000-0000-0000-0000-000000000002"
ADA = GpuMemory(
    0,
    49140,
    48000,
    "NVIDIA RTX 6000 Ada Generation",
    UUID,
    "00000000:01:00.0",
    "8.9",
    "580.178.04",
)
GEFORCE = replace(ADA, total_mib=24564, free_mib=23000, name="NVIDIA GeForce RTX 4090")


def loaded(**env):
    return load_adaptive_catalog(ROOT, {"VLLM_IMAGE": _SHARED_IMAGE, **env})


def snapshot(*devices):
    return HostResourceSnapshot(tuple(devices), 32000)


@pytest.mark.parametrize(
    "device,variant,batch", [(GEFORCE, "rtx4090-24gb", 4096), (ADA, None, 50000)]
)
def test_total_memory_selects_existing_policy_without_changing_model_identity(
    device, variant, batch
):
    catalog, policy, resolver = loaded()
    assignment, reason = resolver.choose(snapshot(device))
    assert reason is None
    assert assignment.profile.resource_variant == variant
    assert assignment.profile.engine_policy()["max_num_batched_tokens"] == batch
    assert assignment.profile.model_id == catalog.profiles["gemma4-e4b-it"].model_id
    assert assignment.profile.revision == catalog.profiles["gemma4-e4b-it"].revision
    assert (
        assignment.profile.gateway_policy
        == catalog.profiles["gemma4-e4b-it"].gateway_policy
    )


def test_busy_48gb_gpu_keeps_reference_policy_instead_of_downgrading():
    _, _, resolver = loaded()
    assignment, reason = resolver.choose(snapshot(replace(ADA, free_mib=30000)))
    assert reason == "GPU_MEMORY_INSUFFICIENT"
    assert assignment.profile.resource_variant is None
    assert assignment.profile.engine_policy()["max_num_batched_tokens"] == 50000


def test_known_name_is_not_a_hardware_allowlist():
    _, _, resolver = loaded()
    for device in (
        replace(ADA, name="Future GPU"),
        replace(ADA, name="NVIDIA RTX A6000", compute_capability="8.6"),
    ):
        assignment, reason = resolver.choose(snapshot(device))
        assert reason is None
        assert assignment.device.name == device.name
        assert assignment.profile.resource_variant is None


@pytest.mark.parametrize(
    "device,reason",
    [
        (replace(ADA, uuid=None), "GPU_IDENTITY_UNAVAILABLE"),
        (replace(ADA, compute_capability=None), "GPU_COMPATIBILITY_UNKNOWN"),
        (replace(ADA, compute_capability="7.0"), "GPU_COMPATIBILITY_UNSUPPORTED"),
    ],
)
def test_missing_identity_and_incompatible_capability_do_not_admit(device, reason):
    _, _, resolver = loaded()
    assignment, blocked = resolver.choose(snapshot(device))
    assert assignment is None and blocked == reason


def test_operator_policy_wins_over_auto_and_legacy_override():
    _, _, resolver = loaded(MAIN_MODEL_RESOURCE_VARIANT="rtx4090-24gb")
    assignment, reason = resolver.choose(snapshot(ADA))
    assert reason is None and assignment.profile.resource_variant == "rtx4090-24gb"
    assert assignment.policy_source == "operator"
    _, _, resolver = loaded(
        MAIN_MODEL_RESOURCE_VARIANT="rtx4090-24gb",
        ADAPTIVE_GPU_RESOURCE_POLICY="reference",
    )
    assignment, reason = resolver.choose(snapshot(ADA))
    assert reason is None and assignment.profile.resource_variant is None
    assert assignment.policy_source == "operator"


def test_policy_and_artifact_failures_have_different_reasons():
    _, _, resolver = loaded(ADAPTIVE_GPU_RESOURCE_POLICY="unknown-variant")
    assert resolver.choose(snapshot(ADA)) == (None, "GPU_RESOURCE_POLICY_UNAVAILABLE")
    _, _, resolver = loaded(VLLM_IMAGE="mutable:tag")
    assert resolver.choose(snapshot(ADA)) == (None, "GPU_ARTIFACT_UNAVAILABLE")


def test_multi_gpu_selects_each_device_policy_without_adding_free_memory():
    _, _, resolver = loaded()
    a = replace(GEFORCE, free_mib=12000)
    b = replace(GEFORCE, index=1, uuid=UUID2, free_mib=12000)
    assignment, reason = resolver.choose(snapshot(a, b))
    assert reason == "GPU_MEMORY_INSUFFICIENT"
    assignment, reason = resolver.choose(snapshot(a, replace(ADA, index=1, uuid=UUID2)))
    assert reason is None and assignment.device.uuid == UUID2
    assert assignment.profile.resource_variant is None


def test_uuid_and_policy_remain_bound_between_plan_and_execution():
    async def scenario():
        catalog, policy, resolver = loaded()
        assignment, reason = resolver.choose(snapshot(ADA))
        assert reason is None
        observations = [snapshot(replace(ADA, index=7))]

        async def reader():
            return observations[0]

        backend = AdaptiveDockerBackend(
            "/var/run/docker.sock",
            "owned",
            config_root=ROOT,
            cpu_cache_dir=ROOT / ".runtime/cpu-models",
            resource_reader=reader,
            selection_policy=policy,
            gpu_policies=resolver,
            gateway_url="http://gateway:9400",
        )
        backend.bind_gpu(assignment)
        await backend._admit_gpu(assignment.profile)
        assert backend.gpu_uuid == UUID
        observations[0] = snapshot(replace(ADA, uuid=UUID2))
        with pytest.raises(RuntimeError, match="GPU_IDENTITY_UNAVAILABLE"):
            await backend._admit_gpu(assignment.profile)
        observations[0] = snapshot(replace(ADA, total_mib=24564, free_mib=23000))
        with pytest.raises(RuntimeError, match="GPU_RESOURCE_POLICY_CHANGED"):
            await backend._admit_gpu(assignment.profile)

    asyncio.run(scenario())


def test_committed_assignment_restores_resource_policy_at_controller_restart(tmp_path):
    import json
    from ai_model_serving.apps.adaptive_controller import create_adaptive_controller_app
    from ai_model_serving.main_model.state import MainModelStateStore
    from tests.support.main_model import FakeBackend

    _, _, resolver = loaded()
    assignment, reason = resolver.choose(snapshot(GEFORCE))
    assert reason is None
    state = MainModelStateStore(tmp_path / "main.json", "cpu-gguf-text")
    state.update(
        lambda s: s.update(
            active_profile="gemma4-e4b-it",
            gate="open",
            runtime_selection={
                "mode": "automatic",
                "reason_code": "GPU_SERVING",
                "gpu_assignment": assignment.public_view(),
            },
        )
    )
    app = create_adaptive_controller_app(
        environment={
            "APP_CONFIG_ROOT": str(ROOT),
            "MAIN_MODEL_STATE_PATH": str(state.path),
            "COMPOSE_PROJECT": "owned",
            "VLLM_IMAGE": _SHARED_IMAGE,
        },
        backend=FakeBackend(),
    )
    restored = app.state.main_model_manager.catalog.profiles["gemma4-e4b-it"]
    assert restored.resource_variant == "rtx4090-24gb"
    assert restored.engine_policy()["max_num_batched_tokens"] == 4096
    assert json.loads(json.dumps(assignment.public_view()))["uuid"] == UUID


def test_gpu_identity_probe_parses_facts_and_never_invents_unknown_values(monkeypatch):
    import subprocess
    import ai_model_serving.host_resource_probe as probe

    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    def result(command, **kwargs):
        assert "compute_cap" in command[1] and "uuid" in command[1]
        return subprocess.CompletedProcess(
            command,
            0,
            f"0, NVIDIA RTX 6000 Ada Generation, {UUID}, 00000000:01:00.0, 8.9, 49140, 48000, 580.178.04\n",
        )

    monkeypatch.setattr(probe.subprocess, "run", result)
    observation = probe.read_host_resource_snapshot()
    assert observation.gpu_observation_error is None
    assert asdict(observation.gpus[0]) == asdict(ADA)


@pytest.mark.parametrize(
    "free_mib,runtime_uuid,allowed",
    [(300, UUID, False), (4000, UUID2, False), (4000, None, False), (4000, UUID, True)],
)
def test_fresh_resource_and_uuid_checks_also_guard_restart_canary(
    monkeypatch, free_mib, runtime_uuid, allowed
):
    from unittest.mock import AsyncMock
    from ai_model_serving.main_model.docker_backend import DockerMainModelBackend

    async def scenario():
        catalog, policy, resolver = loaded()
        assignment, _ = resolver.choose(snapshot(ADA))

        async def reader():
            return snapshot(replace(ADA, free_mib=free_mib))

        backend = AdaptiveDockerBackend(
            "/var/run/docker.sock",
            "owned",
            config_root=ROOT,
            cpu_cache_dir=ROOT / ".runtime/cpu-models",
            resource_reader=reader,
            selection_policy=policy,
            gpu_policies=resolver,
            gateway_url="http://gateway:9400",
        )
        backend.bind_gpu(assignment)
        monkeypatch.setattr(DockerMainModelBackend, "validate", AsyncMock())
        monkeypatch.setattr(
            backend,
            "observe_runtime",
            AsyncMock(return_value={"gpu_device_uuid": runtime_uuid}),
        )
        if allowed:
            await backend.validate(catalog, assignment.profile)
        else:
            with pytest.raises(RuntimeError, match="GPU_REVALIDATION_RESOURCE_UNSAFE"):
                await backend.validate(catalog, assignment.profile)

    asyncio.run(scenario())


def test_adaptive_runtime_identity_includes_full_resource_command():
    from ai_model_serving.main_model.docker_backend import DockerMainModelBackend

    catalog, _, resolver = loaded()
    assignment, _ = resolver.choose(snapshot(GEFORCE))
    profile = assignment.profile
    catalog.profiles[profile.profile_id] = profile
    inspected = {"Config": {"Cmd": list(profile.command), "Image": profile.image}}
    assert (
        DockerMainModelBackend._profile_from_inspected(catalog, inspected)
        == profile.profile_id
    )
    command = inspected["Config"]["Cmd"]
    command[command.index("--max-num-batched-tokens") + 1] = "50000"
    assert DockerMainModelBackend._profile_from_inspected(catalog, inspected) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_variant", []),
        ("policy_source", []),
        ("compute_capability", 89),
        ("total_mib", -1),
        ("uuid", "0"),
    ],
)
def test_invalid_persisted_assignment_is_not_inherited(field, value):
    _, _, resolver = loaded()
    assignment, _ = resolver.choose(snapshot(ADA))
    assert resolver.restore({**assignment.public_view(), field: value}) is None


def test_partially_loaded_gpu_policy_does_not_prevent_cpu_catalog(monkeypatch):
    import ai_model_serving.main_model.adaptive_catalog as module

    original = module.load_main_model_catalog

    def partial(*args, **kwargs):
        if kwargs.get("resource_variant"):
            raise ValueError("invalid variant policy")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "load_main_model_catalog", partial)
    catalog, _, resolver = loaded()
    assert set(catalog.profiles) == {"cpu-gguf-text"}
    assert resolver.choose(snapshot(ADA)) == (None, "GPU_RESOURCE_POLICY_UNAVAILABLE")


def test_unavailable_gpu_artifact_is_reported_before_operator_policy():
    _, _, resolver = loaded(
        VLLM_IMAGE="mutable:tag", MAIN_MODEL_RESOURCE_VARIANT="rtx4090-24gb"
    )
    assert resolver.choose(snapshot(ADA)) == (None, "GPU_ARTIFACT_UNAVAILABLE")
