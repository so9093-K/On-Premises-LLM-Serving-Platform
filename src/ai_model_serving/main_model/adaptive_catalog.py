"""자동 관리의 후보는 기존 CPU/GPU 프로필에서 구성한다."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..configuration import load_yaml_mapping
from ..image_refs import is_immutable_image_ref
from .catalog import MainModelCatalog, load_main_model_catalog
from .cpu_catalog import load_cpu_profile
from .adaptive_gpu import AdaptiveGpuPolicies


def load_adaptive_catalog(
    root: Path, environment: Mapping[str, str]
) -> tuple[MainModelCatalog, dict, AdaptiveGpuPolicies]:
    document = load_yaml_mapping(root / "configs/adaptive_main_model_profiles.yaml")
    selection = dict(document["selection"])
    selection["gpu_budget_ceiling"] = float(
        load_yaml_mapping(root / "configs/gpu_budgets.yaml")["gpu"][
            "total_gpu_memory_utilization"
        ]["avoid_above"]
    )
    cpu_id = selection["cpu_profile"]
    cpu = load_cpu_profile(root, cpu_id, document["runtime"]["container_port"], environment)
    artifact_document = load_yaml_mapping(root / "configs/cpu_model_artifact.yaml")
    profiles = {cpu_id: cpu}
    gpu_error = None
    gpu_profiles = {}
    explicit_value = environment.get("ADAPTIVE_GPU_RESOURCE_POLICY", "").strip()
    legacy_variant = environment.get("MAIN_MODEL_RESOURCE_VARIANT", "").strip()
    selected = (
        explicit_value
        if explicit_value and explicit_value != "auto"
        else legacy_variant
    )
    explicit = bool(selected)
    explicit_variant = None if selected == "reference" else selected or None
    gpu_id = selection["gpu_profile"]
    try:
        gpu_catalog = load_main_model_catalog(
            root / "configs/main_model_profiles.yaml", env=dict(environment)
        )
        reference = gpu_catalog.profiles[gpu_id]
        gpu_profiles[None] = reference
        for variant in reference.resource_variants:
            variant_catalog = load_main_model_catalog(
                root / "configs/main_model_profiles.yaml",
                env=dict(environment),
                resource_variant=variant,
            )
            gpu_profiles[variant] = variant_catalog.profiles[gpu_id]
        profiles[gpu_id] = gpu_profiles.get(explicit_variant, reference)
    except (ValueError, KeyError, RuntimeError):
        # 일부 Variant만 읽힌 상태를 완성된 GPU Catalog로 복원하지 않는다.
        gpu_profiles.clear()
        image = environment.get("MAIN_MODEL_VLLM_IMAGE_OVERRIDE") or environment.get(
            "VLLM_IMAGE"
        )
        gpu_error = (
            "GPU_ARTIFACT_UNAVAILABLE"
            if not image or not is_immutable_image_ref(image)
            else "GPU_RESOURCE_POLICY_UNAVAILABLE"
        )
    gpu_policies = AdaptiveGpuPolicies(
        gpu_profiles,
        selection,
        explicit_variant=explicit_variant,
        explicit=explicit,
        error=gpu_error,
    )
    return (
        MainModelCatalog(
            public_model=cpu.served_model_name,
            default_profile=cpu_id,
            runtime={
                **document["runtime"],
                "adaptive": True,
                "cpu_memory_limit_bytes": int(
                    artifact_document["runtime"]["memory_limit_mib"]
                )
                * 1024
                * 1024,
            },
            profiles=profiles,
        ),
        dict(selection),
        gpu_policies,
    )
