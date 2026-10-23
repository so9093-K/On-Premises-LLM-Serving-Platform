"""관리형 CPU 프리셋은 실제 llama.cpp 명령과 Gateway 제한을 함께 바꾼다."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_model_serving.main_model.cpu import cpu_runtime_command
from ai_model_serving.main_model.cpu_catalog import load_cpu_profile
from ai_model_serving.project_paths import resolve_project_root

CASES = (
    ("cpu-gguf-text-compact", 4096, 1024),
    ("cpu-gguf-text", 8192, 4096),
    ("cpu-gguf-text-extended", 16384, 4096),
)


@pytest.mark.parametrize(("profile_id", "context", "output"), CASES)
def test_cpu_profile_command_and_gateway_policy_agree(
    profile_id: str, context: int, output: int
) -> None:
    root = resolve_project_root()
    profile = load_cpu_profile(root, profile_id, 9401, {})
    args = profile.command
    assert args[args.index("--ctx-size") + 1] == str(context)
    assert args[args.index("--parallel") + 1] == "1"
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert profile.engine_policy()["context_size"] == context
    assert profile.gateway_policy["request_limits"]["max_model_len"] == context
    assert profile.gateway_policy["max_output_tokens"] == output


def test_default_cpu_command_remains_shared_with_compose() -> None:
    args = cpu_runtime_command(resolve_project_root())
    assert args[args.index("--ctx-size") + 1] == "8192"
    assert args[args.index("--threads") + 1] == "4"


def test_unknown_cpu_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown CPU profile"):
        cpu_runtime_command(resolve_project_root(), profile_id="not-declared")

def test_restart_preserves_selected_cpu_profile(tmp_path: Path) -> None:
    """CPU 고정 정책은 Controller 재시작 시 선택한 16K/4K를 8K로 되돌리지 않는다."""
    from dataclasses import dataclass

    from ai_model_serving.main_model.catalog import MainModelCatalog
    from ai_model_serving.main_model.control import MainModelManager
    from ai_model_serving.main_model.state import MainModelStateStore

    profiles = {
        key: load_cpu_profile(resolve_project_root(), key, 9401, {})
        for key, _, _ in CASES
    }
    store = MainModelStateStore(tmp_path / "state.json", "cpu-gguf-text")
    store.update(
        lambda state: state.update(
            active_profile="cpu-gguf-text-extended",
            last_known_good_profile="cpu-gguf-text-extended",
            gate="open",
            runtime_selection={"mode": "cpu"},
        )
    )

    @dataclass
    class ReadyBackend:
        validation_count: int = 0

        async def observed_profile(self, _catalog):
            return "cpu-gguf-text-extended"

        async def observe_runtime(self, _catalog):
            return {"status": "ready", "profile_id": "cpu-gguf-text-extended"}

        async def observed_started_at(self, _catalog):
            return "fixed-container-start"

        async def validate(self, _catalog, profile):
            assert profile.profile_id == "cpu-gguf-text-extended"
            self.validation_count += 1

    backend = ReadyBackend()
    catalog = MainModelCatalog(
        public_model="local-main",
        default_profile="cpu-gguf-text",
        runtime={"startup_timeout_seconds": 30},
        profiles=profiles,
    )
    manager = MainModelManager(catalog, store, backend, boot_profile="cpu-gguf-text")
    import asyncio

    asyncio.run(manager.initialize())
    state = store.read()
    assert state["active_profile"] == "cpu-gguf-text-extended"
    assert state["gate"] == "open"
    assert state["last_operation"] is None
    assert backend.validation_count == 1
