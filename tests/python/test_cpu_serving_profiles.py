"""관리형 CPU 프리셋은 실제 llama.cpp 명령과 Gateway 제한을 함께 바꾼다."""

from __future__ import annotations

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
