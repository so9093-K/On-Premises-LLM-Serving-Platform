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
    ids = ("cpu-gguf-text",)
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
    def __init__(
        self, profile_id: str, *, reject_custom: bool = False,
        reject_rollback: bool = False,
    ):
        self.current = profile_id
        self.reject_custom = reject_custom
        self.reject_rollback = reject_rollback

    async def observed_profile(self, _catalog): return self.current
    async def observed_started_at(self, _catalog): return "container-start-time"
    async def observe_runtime(self, _catalog): return {"status": "ready", "profile_id": self.current}
    async def prepare(self, _catalog, _profile): pass
    async def wait_for_drain(self, _timeout): pass
    async def replace(self, _catalog, profile):
        if self.reject_rollback and self.current.startswith("limits-") and profile.profile_id == "cpu-gguf-text":
            raise RuntimeError("cannot restore previous runtime")
        self.current = profile.profile_id
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
        profile_view = next(p for p in manager.profiles() if p["id"] == active_id)
        assert profile_view["base_profile_id"] == "cpu-gguf-text"
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
        assert not store.read().get("runtime_limit_profiles")
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


def test_new_limit_retains_only_runtime_recovery_profiles(tmp_path: Path):
    """과거 32개 구성에서 새 적용을 끝내면 복구에 필요한 신원만 남는다."""
    async def exercise():
        catalog = cpu_catalog()
        records = {}
        for i in range(32):
            context = 2048 + i * 256
            profile = build_runtime_limit_profile(catalog, "cpu-gguf-text", context, 1024)
            records[profile.profile_id] = {
                "base_profile": "cpu-gguf-text",
                "context_tokens": context,
                "max_output_tokens": 1024,
            }
        protected_id = list(records)[1]
        unresolved_id = list(records)[0]
        unresolved_operation = {
            "id": "unresolved-rollback",
            "requested_profile": unresolved_id,
            "status": "rollback_failed",
            "stage": "rolling_back",
            "previous_profile": "cpu-gguf-text",
            "created_at": 1.0,
            "updated_at": 2.0,
        }
        store = MainModelStateStore(tmp_path / "bounded.json", "cpu-gguf-text")
        store.update(lambda state: state.update(
            active_profile=protected_id,
            last_known_good_profile=protected_id,
            previous_known_good_profile="cpu-gguf-text",
            gate="open",
            runtime_selection={"mode": "cpu"},
            runtime_limit_profiles=records,
            last_operation=unresolved_operation,
            operations=[unresolved_operation],
        ))
        backend = FakeBackend(protected_id)
        manager = MainModelManager(cpu_catalog(), store, backend)
        result = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu",
        )
        assert (await manager.wait_for_operation(result.operation_id))["status"] == "completed"
        saved = store.read()["runtime_limit_profiles"]
        assert len(saved) == 2
        assert protected_id in saved
        assert unresolved_id not in saved
        assert all(item in {protected_id, store.read()["active_profile"]} for item in saved)
        assert all(item not in manager.catalog.profiles for item in set(records) - set(saved))
        assert store.read()["previous_known_good_profile"] == protected_id
        await manager.aclose()
    asyncio.run(exercise())


def test_rollback_failure_keeps_derived_identity_for_recovery(tmp_path: Path):
    """Rollback이 실패하면 관측 중인 파생 런타임의 신원을 정리하지 않는다."""
    async def exercise():
        store = MainModelStateStore(tmp_path / "rollback-failed.json", "cpu-gguf-text")
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text",
            last_known_good_profile="cpu-gguf-text",
            gate="open", runtime_selection={"mode": "cpu"},
        ))
        backend = FakeBackend("cpu-gguf-text", reject_custom=True, reject_rollback=True)
        manager = MainModelManager(cpu_catalog(), store, backend)
        outcome = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu",
        )
        operation = await manager.wait_for_operation(outcome.operation_id)
        state = store.read()
        assert operation["status"] == "rollback_failed"
        assert state["gate"] == "closed"
        assert state["active_profile"] == "cpu-gguf-text"
        assert backend.current.startswith("limits-")
        assert backend.current in state["runtime_limit_profiles"]
        assert backend.current in manager.catalog.profiles
        await manager.aclose()

        restored = MainModelManager(cpu_catalog(), store, backend)
        assert backend.current in restored.catalog.profiles
        assert restored.catalog.profiles[backend.current].command == manager.catalog.profiles[backend.current].command
        assert store.read()["gate"] == "closed"
        await restored.aclose()
    asyncio.run(exercise())


def test_interrupted_switch_with_unknown_runtime_preserves_derived_identity(tmp_path: Path):
    """재시작 시 실제 런타임을 확정할 수 없더라도 복구용 파생 신원을 보존한다."""
    async def exercise():
        store = MainModelStateStore(tmp_path / "interrupted.json", "cpu-gguf-text")
        profile = build_runtime_limit_profile(cpu_catalog(), "cpu-gguf-text", 12288, 2048)
        operation = {
            "id": "interrupted-test",
            "requested_profile": profile.profile_id,
            "previous_profile": "cpu-gguf-text",
            "previous_gate": "open",
            "status": "starting",
            "stage": "starting",
            "created_at": 1.0,
            "updated_at": 1.0,
        }
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text",
            last_known_good_profile="cpu-gguf-text",
            gate="open", runtime_selection={"mode": "cpu"},
            runtime_limit_profiles={profile.profile_id: {
                "base_profile": "cpu-gguf-text", "context_tokens": 12288, "max_output_tokens": 2048,
            }},
            last_operation=operation, operations=[operation],
        ))
        backend = FakeBackend("unrecognized-engine-profile")
        manager = MainModelManager(cpu_catalog(), store, backend)
        await manager.initialize()
        assert store.read()["last_operation"]["status"] == "rollback_failed"
        assert store.read()["gate"] == "closed"
        assert profile.profile_id in store.read()["runtime_limit_profiles"]
        assert profile.profile_id in manager.catalog.profiles
        await manager.aclose()
    asyncio.run(exercise())


def test_idempotent_retry_of_failed_limits_does_not_recreate_orphan(tmp_path: Path):
    """종료된 실패 요청의 중복 응답이 파생 프로필을 다시 남기지 않는다."""
    async def exercise():
        store = MainModelStateStore(tmp_path / "idempotent-retry.json", "cpu-gguf-text")
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text",
            last_known_good_profile="cpu-gguf-text",
            gate="open", runtime_selection={"mode": "cpu"},
        ))
        backend = FakeBackend("cpu-gguf-text", reject_custom=True)
        manager = MainModelManager(cpu_catalog(), store, backend)
        first = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu", client_request_id="same-request",
        )
        assert (await manager.wait_for_operation(first.operation_id))["status"] == "failed"
        assert not store.read().get("runtime_limit_profiles")
        assert not any(p.startswith("limits-") for p in manager.catalog.profiles)
        retry = manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=12288, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu", client_request_id="same-request",
        )
        assert retry.reused is True
        assert retry.operation_id == first.operation_id
        assert not any(p.startswith("limits-") for p in manager.catalog.profiles)
        assert not store.read().get("runtime_limit_profiles")
        await manager.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize("request_id", [0, False, [], {}, "invalid id", ""])
def test_invalid_request_id_is_rejected_without_starting_operation(tmp_path: Path, request_id):
    store = MainModelStateStore(tmp_path / "invalid-request-id.json", "cpu-gguf-text")
    manager = MainModelManager(cpu_catalog(), store, FakeBackend("cpu-gguf-text"))
    with pytest.raises(MainModelSwitchError) as error:
        manager.request_limit_switch(
            "cpu-gguf-text", context_tokens=8192, max_output_tokens=2048,
            confirm_unverified=True, execution_policy="cpu",
            client_request_id=request_id,
        )
    assert error.value.status_code == 422
    assert not store.read().get("operations")
    assert not store.read().get("runtime_limit_profiles")
    assert not any(key.startswith("limits-") for key in manager.catalog.profiles)


def test_failed_restart_validation_preserves_uncertain_derived_profile(tmp_path: Path):
    """재시작 canary 실패 이후 상태가 확정될 때까지 파생 신원을 보존한다."""
    async def exercise():
        store = MainModelStateStore(tmp_path / "failed-restart.json", "cpu-gguf-text")
        profile = build_runtime_limit_profile(cpu_catalog(), "cpu-gguf-text", 12288, 2048)
        operation = {
            "id": "restart-validation",
            "requested_profile": profile.profile_id,
            "previous_profile": "cpu-gguf-text",
            "previous_gate": "open",
            "status": "validating",
            "stage": "validating",
            "created_at": 1.0, "updated_at": 1.0,
        }
        store.update(lambda state: state.update(
            active_profile="cpu-gguf-text",
            last_known_good_profile="cpu-gguf-text",
            gate="open", runtime_selection={"mode": "cpu"},
            runtime_limit_profiles={profile.profile_id: {
                "base_profile": "cpu-gguf-text", "context_tokens": 12288, "max_output_tokens": 2048,
            }},
            last_operation=operation, operations=[operation],
        ))
        backend = FakeBackend(profile.profile_id, reject_custom=True)
        manager = MainModelManager(cpu_catalog(), store, backend)
        with pytest.raises(RuntimeError, match="canary"):
            await manager.initialize()
        manager.record_initialization_failure("canary verification failed after restart")
        state = store.read()
        assert state["gate"] == "closed"
        assert state["last_operation"]["status"] == "failed"
        assert state["last_operation"]["uncertain_runtime"] is True
        assert profile.profile_id in state["runtime_limit_profiles"]
        assert profile.profile_id in manager.catalog.profiles
        await manager.aclose()
        restored = MainModelManager(cpu_catalog(), store, backend)
        assert profile.profile_id in restored.catalog.profiles
        await restored.aclose()
    asyncio.run(exercise())


def test_cpu_profile_view_exposes_context_ceiling(tmp_path: Path):
    catalog = cpu_catalog()
    store = MainModelStateStore(tmp_path / "server-ceiling.json", "cpu-gguf-text")
    manager = MainModelManager(catalog, store, FakeBackend("cpu-gguf-text"))
    assert manager.profiles()[0]["context_tokens_ceiling"] == 16384


def test_cpu_first_initialization_preserves_restorable_custom_limits():
    """GPU Catalog가 없어도 CPU 파생 한도를 8K 기본값으로 초기화하지 않는다."""
    from ai_model_serving.main_model.managed_catalog import active_profile_resolvable

    catalog = cpu_catalog()
    profile = build_runtime_limit_profile(catalog, "cpu-gguf-text", 16384, 4096)
    stored = {
        "active_profile": profile.profile_id,
        "runtime_limit_profiles": {
            profile.profile_id: {
                "base_profile": "cpu-gguf-text",
                "context_tokens": 16384,
                "max_output_tokens": 4096,
            }
        },
    }
    # Manager 복원이 실행되기 전 Catalog에는 파생 ID가 없다.
    assert profile.profile_id not in catalog.profiles
    assert active_profile_resolvable(catalog, stored)
    assert not active_profile_resolvable(
        catalog, {**stored, "runtime_limit_profiles": {}}
    )
    assert not active_profile_resolvable(
        catalog, {**stored, "runtime_limit_profiles": {
            profile.profile_id: {
                "base_profile": "cpu-gguf-text",
                "context_tokens": 8192,
                "max_output_tokens": 4096,
            }
        }}
    )


def test_compose_boot_and_cache_resolve_saved_cpu_server_limits(tmp_path: Path):
    """Controller 복원보다 먼저 실행되는 Compose/Cache도 사용자 한도 신원을 읽는다."""
    from ai_model_serving.main_model.boot import render_boot_override
    from ai_model_serving.main_model.runtime_limits import cache_profile_for_persisted_limit

    root = resolve_project_root()
    base_catalog = cpu_catalog()
    custom = build_runtime_limit_profile(base_catalog, "cpu-gguf-text", 16384, 4096)
    state_path = tmp_path / "main-model-state.json"
    store = MainModelStateStore(state_path, "cpu-gguf-text")
    store.update(lambda state: state.update(
        active_profile=custom.profile_id,
        last_known_good_profile=custom.profile_id,
        gate="open",
        runtime_selection={"mode": "cpu"},
        runtime_limit_profiles={custom.profile_id: {
            "base_profile": "cpu-gguf-text",
            "context_tokens": 16384,
            "max_output_tokens": 4096,
        }},
    ))
    resolved = cache_profile_for_persisted_limit(
        cpu_catalog(), custom.profile_id, state_path
    )
    assert resolved.model_id == base_catalog.profiles["cpu-gguf-text"].model_id
    assert resolved.revision == base_catalog.profiles["cpu-gguf-text"].revision
    assert resolved.command[resolved.command.index("--ctx-size") + 1] == "16384"

    env_path = tmp_path / "cpu.env"
    env_path.write_text(
        "VLLM_IMAGE=sha256:" + "a" * 64 + "\n"
        "MAIN_MODEL_BOOT_PROFILE=cpu-gguf-text\n"
        "MAIN_MODEL_PROFILE_LOCKED=false\n",
        encoding="utf-8",
    )
    profile_id, override = render_boot_override(
        catalog_path=root / "configs/main_model_profiles.yaml",
        state_path=state_path,
        env_path=env_path,
    )
    assert profile_id == custom.profile_id
    command = override["services"]["main-llm-vllm"]["command"]
    assert command[command.index("--ctx-size") + 1] == "16384"
