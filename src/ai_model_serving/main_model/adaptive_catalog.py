"""자동 관리의 후보는 기존 CPU/GPU 프로필에서 구성한다."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..configuration import load_yaml_mapping
from ..image_refs import is_immutable_image_ref
from ..serving_profile import load_main_serving_catalog
from .catalog import MainModelCatalog, MainModelProfile, load_main_model_catalog
from .cpu import cpu_runtime_command
from .engine_policy import CpuEnginePolicy


def load_adaptive_catalog(
    root: Path, environment: Mapping[str, str]
) -> tuple[MainModelCatalog, dict, str | None]:
    document = load_yaml_mapping(root / "configs/adaptive_main_model_profiles.yaml")
    selection = dict(document["selection"])
    selection["gpu_budget_ceiling"] = float(
        load_yaml_mapping(root / "configs/gpu_budgets.yaml")["gpu"][
            "total_gpu_memory_utilization"
        ]["avoid_above"]
    )
    serving = load_main_serving_catalog(root / "configs/cpu_main_model_profiles.yaml")
    cpu_document = load_yaml_mapping(root / "configs/cpu_main_model_profiles.yaml")
    artifact_document = load_yaml_mapping(root / "configs/cpu_model_artifact.yaml")
    artifact = artifact_document["model"]
    cpu_id = selection["cpu_profile"]
    cpu = serving.profiles[cpu_id]
    image = (
        environment.get("LLAMA_CPP_IMAGE")
        or load_yaml_mapping(root / "configs/recommended_images.yaml")["images"][
            "llama_cpp"
        ]["default"]
    )
    if not is_immutable_image_ref(image):
        raise ValueError("LLAMA_CPP_IMAGE must be an immutable image reference")
    profiles = {
        cpu_id: MainModelProfile(
            profile_id=cpu_id,
            display_name=cpu.display_name,
            model_id=artifact["repo_id"],
            revision=artifact["revision"],
            served_model_name=serving.public_model,
            command=cpu_runtime_command(
                root, port=document["runtime"]["container_port"]
            ),
            compatibility=cpu.compatibility,
            qualification=cpu.qualification,
            capabilities={"deployed_input": list(cpu.deployed_input)},
            gateway_policy=cpu.gateway_policy,
            image=image,
            runtime_backend="llama-cpp",
            resolved_engine_policy=CpuEnginePolicy(
                cpu_document["runtime"]["context_size"],
                cpu_document["runtime"]["parallel"],
            ),
        )
    }
    gpu_error = None
    try:
        gpu_catalog = load_main_model_catalog(
            root / "configs/main_model_profiles.yaml",
            env=dict(environment),
            resource_variant=environment.get("MAIN_MODEL_RESOURCE_VARIANT")
            or selection["gpu_resource_variant"],
        )
        gpu_id = selection["gpu_profile"]
        profile = gpu_catalog.profiles[gpu_id]
        if gpu_catalog.missing_selected_resource_policy(gpu_id):
            raise ValueError(
                "GPU profile does not declare the selected resource variant"
            )
        profiles[gpu_id] = profile
    except (ValueError, KeyError, RuntimeError):
        # GPU Artifact 미준비는 CPU 설정과 기동을 막지 않는다.
        gpu_error = "GPU_ARTIFACT_UNAVAILABLE"
    return (
        MainModelCatalog(
            public_model=serving.public_model,
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
        gpu_error,
    )
