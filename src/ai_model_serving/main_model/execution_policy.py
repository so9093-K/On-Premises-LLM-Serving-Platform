"""CLI와 Controller가 공유하는 관리형 Main 실행 정책의 우선순위."""

from collections.abc import Mapping

from ..settings_parts.env import as_bool

EXECUTION_POLICIES = ("fallback", "automatic", "cpu", "gpu")
RECOVERING_POLICIES = frozenset({"fallback", "automatic"})
CPU_FIRST_POLICIES = RECOVERING_POLICIES | {"cpu"}


def resolve_execution_policy(state: Mapping, environment: Mapping[str, str]) -> str:
    """영속 선택, 최초 seed, CPU 의도, 기본 CPU 복구 순서로 판단한다."""
    mode = (state.get("runtime_selection") or {}).get("mode") or environment.get("MAIN_MODEL_EXECUTION_POLICY")
    locked = as_bool(environment.get("MAIN_MODEL_PROFILE_LOCKED"), False)
    locked_engine = "cpu" if environment.get("MAIN_MODEL_BOOT_PROFILE") == "cpu-gguf-text" else "gpu"
    if not mode:
        profile = state.get("active_profile") or environment.get("MAIN_MODEL_BOOT_PROFILE")
        mode = locked_engine if locked else "cpu" if profile == "cpu-gguf-text" else "fallback"
    if mode not in EXECUTION_POLICIES:
        raise ValueError("invalid MAIN_MODEL_EXECUTION_POLICY")
    if locked and mode != locked_engine:
        raise ValueError("MAIN_MODEL_PROFILE_LOCKED requires a fixed policy matching MAIN_MODEL_BOOT_PROFILE")
    return mode
