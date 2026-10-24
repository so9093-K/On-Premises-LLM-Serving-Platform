"""미지원 Target은 자동 변환하거나 기존 설정을 덮어쓰지 않는다."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.config.setup_env import main as setup_env_main, sync_deployment_target, sync_env_keys


@pytest.mark.parametrize("obsolete", ["linux-cpu-managed", "linux-adaptive"])
def test_stale_target_is_rejected_without_modifying_environment(
    tmp_path: Path, obsolete: str
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "BUILD_PROFILE=compose\n"
        f"DEPLOYMENT_TARGET={obsolete}\n"
        "MAIN_MODEL_BOOT_PROFILE=cpu-gguf-text\n"
        "API_KEY=leave-unchanged\n",
        encoding="utf-8",
    )
    initial = env.read_bytes()
    for selected, profile in (
        ("linux-nvidia-dynamic", "cpu-gguf-text"),
        ("linux-core", None),
    ):
        with pytest.raises(ValueError, match="지원하지 않습니다"):
            sync_deployment_target(env, selected, main_profile=profile)
        assert env.read_bytes() == initial



@pytest.mark.parametrize("obsolete", ["linux-cpu-managed", "linux-adaptive"])
def test_sync_env_rejects_old_target_before_template_mutation(
    tmp_path: Path, obsolete: str
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "BUILD_PROFILE=compose\n"
        f"DEPLOYMENT_TARGET={obsolete}\n"
        "API_KEY=leave-unchanged\n",
        encoding="utf-8",
    )
    initial = env.read_bytes()
    with pytest.raises(ValueError, match="지원하지 않습니다"):
        sync_env_keys(env)
    assert env.read_bytes() == initial
    result = setup_env_main(["--sync-env", "--env-file", str(env),
                             "--deployment-target", "linux-nvidia-dynamic"])
    assert result == 2
    assert env.read_bytes() == initial
