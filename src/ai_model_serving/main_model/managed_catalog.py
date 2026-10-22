"""GPU Artifact 준비와 CPU/Core 생명주기를 분리한다."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .adaptive_catalog import load_adaptive_catalog
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
