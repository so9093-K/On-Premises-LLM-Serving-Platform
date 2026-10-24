"""GPU Artifact 준비와 CPU/Core 생명주기를 분리한다."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .adaptive_catalog import load_adaptive_catalog
from .runtime_limits import RuntimeLimitError, build_runtime_limit_profile
from .catalog import MainModelConfigurationError, load_main_model_catalog, gpu_util_override_from_mapping, resource_variant_from_mapping


def load_managed_catalog(root: Path, environment: Mapping[str, str], *, cpu_available: bool, catalog_path: Path | None = None):
    try:
        return load_main_model_catalog(
            (catalog_path or root / "configs/main_model_profiles.yaml"), env=dict(environment),
            gpu_memory_utilization_override=gpu_util_override_from_mapping(environment),
            resource_variant=resource_variant_from_mapping(environment),
        )
    except MainModelConfigurationError:
        if not cpu_available:
            raise
        catalog, _, _ = load_adaptive_catalog(root, environment)
        # 전체 GPU Catalog가 유효해질 때 Controller 재시작으로 공개한다.
        return catalog


def active_profile_resolvable(catalog, state: dict) -> bool:
    """CPU 우선 부팅의 GPU 부재 처리에서 복원 전 파생 CPU 신원을 보호한다.

    복원 검증은 MainModelManager가 계속 소유한다. 여기서는 GPU Catalog를
    사용할 수 없는 경우 기존 GPU 신원을 CPU 복구로 넘겨도 되는지만 판정한다.
    """
    active_id = state.get("active_profile")
    if active_id is None or active_id in catalog.profiles:
        return True
    records = state.get("runtime_limit_profiles")
    record = records.get(active_id) if isinstance(records, dict) else None
    if not isinstance(record, dict):
        return False
    if record.get("base_profile") not in catalog.profiles:
        return False
    try:
        restored = build_runtime_limit_profile(
            catalog, record["base_profile"], record["context_tokens"],
            record["max_output_tokens"],
        )
    except (RuntimeLimitError, KeyError, TypeError):
        return False
    return restored.profile_id == active_id
