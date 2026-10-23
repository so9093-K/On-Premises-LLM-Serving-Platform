"""하나의 CPU 기준 프로필과 사용자 지정 서버 한도의 공통 실행 계약."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ai_model_serving.main_model.catalog import MainModelCatalog
from ai_model_serving.main_model.control import MainModelManager
from ai_model_serving.main_model.cpu import cpu_runtime_command
from ai_model_serving.main_model.cpu_catalog import load_cpu_profile
from ai_model_serving.main_model.runtime_limits import (
    CPU_MAX_CONTEXT_TOKENS,
    RuntimeLimitError,
    build_runtime_limit_profile,
)
from ai_model_serving.main_model.state import MainModelStateStore
from ai_model_serving.project_paths import resolve_project_root


def _catalog() -> MainModelCatalog:
    return MainModelCatalog(
        public_model="local-main",
        default_profile="cpu-gguf-text",
        runtime={"startup_timeout_seconds": 30},
        profiles={
            "cpu-gguf-text": load_cpu_profile(
                resolve_project_root(), "cpu-gguf-text", 9401, {}
            )
        },
    )


def test_default_cpu_profile_command_and_gateway_policy_agree() -> None:
    profile = _catalog().profiles["cpu-gguf-text"]
    args = profile.command
    assert args[args.index("--ctx-size") + 1] == "8192"
    assert args[args.index("--parallel") + 1] == "1"
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert profile.engine_policy()["context_size"] == 8192
    assert profile.gateway_policy["request_limits"]["max_model_len"] == 8192
    assert profile.gateway_policy["max_output_tokens"] == 4096


@pytest.mark.parametrize(("context", "output"), [(4096, 1024), (16384, 4096)])
def test_cpu_limits_are_runtime_variants_not_distinct_model_profiles(
    context: int, output: int
) -> None:
    catalog = _catalog()
    derived = build_runtime_limit_profile(catalog, "cpu-gguf-text", context, output)
    assert len(catalog.profiles) == 1
    assert derived.command[derived.command.index("--ctx-size") + 1] == str(context)
    assert derived.gateway_policy["request_limits"]["max_model_len"] == context
    assert derived.gateway_policy["max_output_tokens"] == output
    assert derived.model_id == catalog.profiles["cpu-gguf-text"].model_id
    assert derived.revision == catalog.profiles["cpu-gguf-text"].revision
    assert CPU_MAX_CONTEXT_TOKENS == 16384


def test_default_cpu_command_is_shared() -> None:
    args = cpu_runtime_command(resolve_project_root())
    assert args[args.index("--ctx-size") + 1] == "8192"
    assert args[args.index("--threads") + 1] == "4"


@pytest.mark.parametrize("profile_id", [
    "not-declared", "cpu-gguf-text-compact", "cpu-gguf-text-extended",
])
def test_noncanonical_cpu_profiles_are_rejected(profile_id: str) -> None:
    with pytest.raises(ValueError, match="unknown CPU profile"):
        cpu_runtime_command(resolve_project_root(), profile_id=profile_id)


def test_explicit_cpu_ceiling_rejects_larger_context() -> None:
    with pytest.raises(RuntimeLimitError, match="512..16384"):
        build_runtime_limit_profile(_catalog(), "cpu-gguf-text", 16385, 4096)


def test_restart_preserves_custom_cpu_runtime(tmp_path: Path) -> None:
    """Controller 재시작이 사용자 지정 16K를 8K 기본 설정으로 바꾸지 않는다."""
    catalog = _catalog()
    derived = build_runtime_limit_profile(catalog, "cpu-gguf-text", 16384, 4096)
    store = MainModelStateStore(tmp_path / "state.json", "cpu-gguf-text")
    store.update(lambda state: state.update(
        active_profile=derived.profile_id,
        last_known_good_profile=derived.profile_id,
        gate="open",
        runtime_selection={"mode": "cpu"},
        runtime_limit_profiles={derived.profile_id: {
            "base_profile": "cpu-gguf-text",
            "context_tokens": 16384,
            "max_output_tokens": 4096,
        }},
    ))

    class ReadyBackend:
        validation_count = 0

        async def observed_profile(self, _catalog):
            return derived.profile_id

        async def observe_runtime(self, _catalog):
            return {"status": "ready", "profile_id": derived.profile_id}

        async def observed_started_at(self, _catalog):
            return "fixed-container-start"

        async def validate(self, _catalog, profile):
            assert profile.profile_id == derived.profile_id
            self.validation_count += 1

    backend = ReadyBackend()
    manager = MainModelManager(_catalog(), store, backend, boot_profile="cpu-gguf-text")
    asyncio.run(manager.initialize())
    assert store.read()["active_profile"] == derived.profile_id
    assert store.read()["gate"] == "open"
    assert backend.validation_count == 1
