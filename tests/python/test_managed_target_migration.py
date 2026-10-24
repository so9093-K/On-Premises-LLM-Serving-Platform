"""폐기된 Target 이전은 명시적이고 손실 범위가 Main 상태에 한정된다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.migrate_managed_target import migrate_environment


def _fixture(root: Path, target: str = "linux-cpu-managed") -> tuple[Path, Path]:
    env = root / ".env"
    env.write_text(
        f"BUILD_PROFILE=compose\nDEPLOYMENT_TARGET={target}\n"
        "MAIN_MODEL_STATIC_PROFILE=cpu-gguf-text-extended\n"
        "MAIN_MODEL_BASE_URL=http://cpu-main:8080/v1\n"
        "API_KEYS=keep-public-key\nADMIN_API_KEYS=keep-admin-key\n"
        "INTERNAL_SERVICE_TOKEN=keep-internal-token\n"
        "PLATFORM_PORT_BASE=18000\nCUSTOM_OPERATOR_SETTING=keep-me\n",
        encoding="utf-8",
    )
    env.chmod(0o600)
    state = root / ".runtime/main-model/main-model-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({
        "schema_version": 1, "generation": 2,
        "active_profile": "cpu-gguf-text-extended", "gate": "open",
        "operations": [], "runtime_limit_profiles": {},
    }), encoding="utf-8")
    (root / ".runtime" / "keep.json").write_text("unrelated", encoding="utf-8")
    (root / "model-cache").mkdir()
    (root / "model-cache" / "weights.gguf").write_text("untouched")
    return env, state


def _projection(target: str, profile: str | None) -> dict[str, str]:
    assert target == "linux-nvidia-dynamic"
    assert profile == "cpu-gguf-text"
    return {"MAIN_MODEL_BASE_URL": "http://main-llm-vllm:9401/v1"}


@pytest.mark.parametrize("old_target", ["linux-cpu-managed", "linux-adaptive"])
def test_migration_is_plan_first_and_preserves_credentials_and_cache(tmp_path, old_target):
    env, state = _fixture(tmp_path, old_target)
    original = env.read_bytes()
    plan = migrate_environment(
        tmp_path, policy="cpu", projection=_projection,
        ownership_check=lambda root: [],
    )
    assert plan["applied"] is False
    assert env.read_bytes() == original
    assert state.exists()
    result = migrate_environment(
        tmp_path, policy="cpu", projection=_projection,
        ownership_check=lambda root: [], confirmed=True,
    )
    assert result["applied"] is True
    contents = env.read_text()
    assert "DEPLOYMENT_TARGET=linux-nvidia-dynamic" in contents
    assert "MAIN_MODEL_EXECUTION_POLICY=cpu" in contents
    assert "MAIN_MODEL_BOOT_PROFILE=cpu-gguf-text" in contents
    assert "MAIN_MODEL_BASE_URL=http://main-llm-vllm:9401/v1" in contents
    assert "MAIN_MODEL_STATIC_PROFILE=" not in contents
    for value in (
        "API_KEYS=keep-public-key", "ADMIN_API_KEYS=keep-admin-key",
        "INTERNAL_SERVICE_TOKEN=keep-internal-token",
        "PLATFORM_PORT_BASE=18000", "CUSTOM_OPERATOR_SETTING=keep-me",
    ):
        assert value in contents
    assert env.stat().st_mode & 0o777 == 0o600
    assert not state.exists()
    assert Path(result["backup_env"]).read_bytes() == original
    assert Path(result["backup_env"]).stat().st_mode & 0o777 == 0o600
    assert Path(result["backup_state"]).exists()
    assert (tmp_path / ".runtime" / "keep.json").read_text() == "unrelated"
    assert (tmp_path / "model-cache" / "weights.gguf").read_text() == "untouched"
    with pytest.raises(ValueError, match="삭제된 관리형 Target"):
        migrate_environment(
            tmp_path, policy="cpu", projection=_projection,
            ownership_check=lambda root: [], confirmed=True,
        )


def test_migration_refuses_running_containers_without_mutation(tmp_path):
    env, state = _fixture(tmp_path)
    before = env.read_bytes()
    with pytest.raises(RuntimeError, match="컨테이너"):
        migrate_environment(
            tmp_path, policy="cpu", confirmed=True, projection=_projection,
            ownership_check=lambda root: ["running-checkout-container"],
        )
    assert env.read_bytes() == before
    assert state.exists()
    assert not (tmp_path / ".runtime/migrations").exists()


@pytest.mark.parametrize("policy,profile", [
    ("gpu", None),
    ("fallback", "gemma4-e4b-it"),
    ("nonexistent", None),
    ("gpu", "cpu-gguf-text"),
])
def test_migration_rejects_unsupported_policy_or_profile(tmp_path, policy, profile):
    env, state = _fixture(tmp_path)
    before = env.read_bytes()
    with pytest.raises(ValueError):
        migrate_environment(
            tmp_path, policy=policy, profile=profile, projection=_projection,
            ownership_check=lambda root: [],
        )
    assert env.read_bytes() == before
    assert state.exists()


def test_migration_rejects_corrupt_state_instead_of_discarding_it(tmp_path):
    env, state = _fixture(tmp_path)
    state.write_text("{broken", encoding="utf-8")
    before = env.read_bytes()
    with pytest.raises(RuntimeError):
        migrate_environment(
            tmp_path, policy="cpu", confirmed=True, projection=_projection,
            ownership_check=lambda root: [],
        )
    assert env.read_bytes() == before
    assert state.read_text() == "{broken"


def test_migration_does_not_accept_arbitrary_or_static_target(tmp_path):
    env, state = _fixture(tmp_path, "linux-cpu-static")
    with pytest.raises(ValueError, match="삭제된 관리형 Target"):
        migrate_environment(tmp_path, policy="cpu", projection=_projection)
    assert env.exists() and state.exists()


@pytest.mark.parametrize(("policy", "profile"), [
    ("cpu", None),
    ("fallback", None),
    ("gpu", "gemma4-e4b-it"),
])
def test_migration_plan_resolves_real_managed_catalog(tmp_path: Path, policy, profile):
    """Mock projection 없이 현재 Target/기준 프로필 선언에 맞는 주소를 확인한다."""
    _fixture(tmp_path)
    result = migrate_environment(
        tmp_path, policy=policy, profile=profile, confirmed=False,
    )
    assert result["to"] == "linux-nvidia-dynamic"
    assert result["profile"] == (profile or "cpu-gguf-text")
    assert result["applied"] is False
