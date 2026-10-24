"""미지원 Target은 자동 변환하거나 기존 설정을 덮어쓰지 않는다."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.config.setup_env import sync_deployment_target


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
    with pytest.raises(ValueError, match="지원하지 않습니다"):
        sync_deployment_target(
            env, "linux-nvidia-dynamic", main_profile="cpu-gguf-text"
        )
    assert env.read_bytes() == initial
