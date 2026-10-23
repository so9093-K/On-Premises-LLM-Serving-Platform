"""서버 토큰 한도의 Engine/Gateway 동기화와 안전한 전환·복원 계약."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from ai_model_serving.main_model.catalog import MainModelCatalog
from ai_model_serving.main_model.control import MainModelManager, MainModelSwitchError
from ai_model_serving.main_model.cpu_catalog import load_cpu_profile
from ai_model_serving.main_model.engine_policy import VllmEnginePolicy
from ai_model_serving.main_model.runtime_limits import (
    RuntimeLimitError, build_runtime_limit_profile, restore_runtime_limit_profiles,
)
from ai_model_serving.main_model.state import MainModelStateStore
from ai_model_serving.project_paths import resolve_project_root


def cpu_catalog() -> MainModelCatalog:
    ids = ("cpu-gguf-text-compact", "cpu-gguf-text", "cpu-gguf-text-extended")
    return MainModelCatalog(
        public_model="local-main",
        default_profile="cpu-gguf-text",
        runtime={"startup_timeout_seconds": 10, "drain_timeout_seconds": 1},
        profiles={key: load_cpu_profile(resolve_project_root(), key, 9401, {}) for key in ids},
    )


def test_cpu_context_and_gateway_output_change_together():
    catalog = cpu_catalog()
    profile = build_runtime_limit_profile(catalog, "cpu-gguf-text", 12288, 2048)
    assert profile.profile_id.startswith("limits-")
    assert profile.command[profile.command.index("--ctx-size") + 1] == "12288"
    assert profile.gateway_policy["request_limits"]["max_model_len"] == 12288
    assert profile.gateway_policy["max_output_tokens"] == 2048
    assert profile.resolved_engine_policy.context_size == 12288
    assert profile.model_id == catalog.profiles["cpu-gguf-text"].model_id
    assert profile.revision == catalog.profiles["cpu-gguf-text"].revision
    assert profile.image == catalog.profiles["cpu-gguf-text"].image
    assert profile.qualification["status"] == "unverified"


@pytest.mark.parametrize(("context", "output"), [
    (0, 100), (True, 100), ("8192", 512), (32768, 512),
    (4096, 4097), (8192, False),
])
def test_invalid_cpu_limits_fail_before_runtime(context, output):
    with pytest.raises(RuntimeLimitError):
        build_runtime_limit_profile(cpu_catalog(), "cpu-gguf-text", context, output)


def test_gpu_cannot_exceed_declared_context_and_updates_command_and_gateway():
    catalog = cpu_catalog()
    cpu = catalog.profiles["cpu-gguf-text"]
    gpu = replace(
        cpu, profile_id="gpu-reference", runtime_backend="vllm-cuda",
        command=("--max-model-len", "8192", "--max-num-seqs", "4", "--gpu-memory-utilization", "0.75"),
        resolved_engine_policy=VllmEnginePolicy.from_command((
            "--max-model-len", "8192", "--max-num-seqs", "4", "--gpu-memory-utilization", "0.75",
        )),
    )
    catalog.profiles[gpu.profile_id] = gpu
    custom = build_runtime_limit_profile(catalog, "gpu-reference", 6144, 2048)
    assert custom.command[1] == "6144"
    assert custom.resolved_engine_policy.max_model_len == 6144
    assert custom.gateway_policy["max_output_tokens"] == 2048
    assert custom.gateway_policy["request_limits"]["max_model_len"] == 6144
    assert custom.vram_fraction == gpu.vram_fraction
    with pytest.raises(RuntimeLimitError, match="GPU context"):
        build_runtime_limit_profile(catalog, "gpu-reference", 12288, 1024)


class FakeBackend:
    def __init__(self, profile_id: str, *, reject_custom: bool = False):
        self.current = profile_id
        self.reject_custom = reject_custom

    async def observed_profile(self, _catalog): return self.current
    async def observed_started_at(self, _catalog): return "container-start-time"
    async def observe_runtime(self, _catalog): return {"status": "ready", "profile_id": self.current}
    async def prepare(self, _catalog, _profile): pass
    async def wait_for_drain(self, _timeout): pass
    async def replace(self, _catalog, profile): self.current = profile.profile_id
    async def validate(self, _catalog, profile):
        if self.reject_custom and profile.profile_id.startswith("limits-"):
            raise RuntimeError("test canary rejected new runtime")
        assert self.current == profile.profile_id


def test_custom_cpu_apply_and_restart_restore(tmp_path: Path):
    async def exercise():
        store = MainModelStateStore(tmp_path / "runtime.json", "cpu-gguf-text")
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text", last_known_good_profile="cpu-gguf-text",
            gate="open", runtime_selection={"mode": "cpu"},
        ))
        backend = FakeBackend("cpu-gguf-text")
        manager = MainModelManager(cpu_catalog(), store, backend)
        outcome = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu",
        )
        result = await manager.wait_for_operation(outcome.operation_id)
        assert result["status"] == "completed"
        active_id = store.read()["active_profile"]
        assert active_id == backend.current
        assert active_id.startswith("limits-")
        assert manager.catalog.profiles[active_id].gateway_policy["max_output_tokens"] == 2048
        await manager.aclose()
        restarted = MainModelManager(cpu_catalog(), store, backend)
        await restarted.initialize()
        assert restarted.catalog.profiles[active_id].engine_policy()["context_size"] == 12288
        assert store.read()["active_profile"] == active_id
        assert store.read()["gate"] == "open"
        await restarted.aclose()
    asyncio.run(exercise())


def test_failed_canary_restores_entire_previous_runtime(tmp_path: Path):
    async def exercise():
        store = MainModelStateStore(tmp_path / "rollback.json", "cpu-gguf-text")
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text", last_known_good_profile="cpu-gguf-text", gate="open",
        ))
        backend = FakeBackend("cpu-gguf-text", reject_custom=True)
        manager = MainModelManager(cpu_catalog(), store, backend)
        outcome = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu",
        )
        result = await manager.wait_for_operation(outcome.operation_id)
        assert result["status"] == "failed"
        assert backend.current == "cpu-gguf-text"
        assert store.read()["active_profile"] == "cpu-gguf-text"
        assert store.read()["gate"] == "open"
        await manager.aclose()
    asyncio.run(exercise())


def test_corrupted_persisted_limits_fail_closed():
    catalog = cpu_catalog()
    with pytest.raises(RuntimeLimitError):
        restore_runtime_limit_profiles(catalog, {"limits-forged": {
            "base_profile": "cpu-gguf-text", "context_tokens": 12288, "max_output_tokens": 2048,
        }})


def test_custom_limits_do_not_override_automatic_fallback_policy(tmp_path: Path):
    store = MainModelStateStore(tmp_path / "automatic.json", "cpu-gguf-text")
    manager = MainModelManager(cpu_catalog(), store, FakeBackend("cpu-gguf-text"))
    with pytest.raises(MainModelSwitchError, match="fixed CPU or GPU"):
        manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="automatic",
        )
    assert not store.read().get("runtime_limit_profiles")
