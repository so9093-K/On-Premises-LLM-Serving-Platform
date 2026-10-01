from __future__ import annotations

from pathlib import Path

from ai_model_serving.apps.runtime_controller import load_runtime_controller_config
from ai_model_serving.platform_state import (
    DEFAULT_PLATFORM_STATE_DIR,
    configured_platform_state_root,
    gateway_runtime_state_path,
    operator_configuration_state_path,
    platform_state_path,
)


def test_local_run_has_no_persistent_root_without_opt_in() -> None:
    environment: dict[str, str] = {}

    assert configured_platform_state_root(environment) is None
    assert platform_state_path("runtime-state.json", environment=environment) is None
    assert operator_configuration_state_path(environment) is None


def test_platform_state_children_derive_from_one_configured_root(tmp_path: Path) -> None:
    environment = {"PLATFORM_STATE_DIR": str(tmp_path)}

    assert configured_platform_state_root(environment) == tmp_path
    assert gateway_runtime_state_path(environment) == tmp_path / "runtime-state.json"
    assert operator_configuration_state_path(environment) == (
        tmp_path / "config" / "operator-overrides.yaml"
    )


def test_container_default_root_is_explicit_boundary_fallback() -> None:
    environment: dict[str, str] = {}

    assert platform_state_path(
        "main-model-state.json",
        environment=environment,
        default_root=DEFAULT_PLATFORM_STATE_DIR,
    ) == DEFAULT_PLATFORM_STATE_DIR / "main-model-state.json"


def test_runtime_controller_state_children_follow_platform_state_root(tmp_path: Path) -> None:
    state_root = tmp_path / "platform-state"
    config = load_runtime_controller_config(
        {
            "APP_CONFIG_ROOT": str(Path(".").resolve()),
            "PLATFORM_STATE_DIR": str(state_root),
            "INTERNAL_SERVICE_AUTH_REQUIRED": "false",
        }
    )

    assert config.state_path == state_root / "main-model-state.json"
    assert config.log_target_manifest_path == (
        state_root / "log-targets" / "docker-containers.json"
    )
