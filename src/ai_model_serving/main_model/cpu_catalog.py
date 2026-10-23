"""관리형 CPU 프로필은 단일 Serving·Artifact 계약에서 조립한다."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..configuration import load_yaml_mapping
from ..image_refs import is_immutable_image_ref
from ..serving_profile import load_main_serving_catalog
from .catalog import MainModelProfile
from .cpu import cpu_runtime_command
from .engine_policy import CpuEnginePolicy


def load_cpu_profile(
    root: Path, profile_id: str, port: int, environment: Mapping[str, str]
) -> MainModelProfile:
    serving = load_main_serving_catalog(root / "configs/cpu_main_model_profiles.yaml")
    profile = serving.profiles[profile_id]
    document = load_yaml_mapping(root / "configs/cpu_main_model_profiles.yaml")
    artifact = load_yaml_mapping(root / "configs/cpu_model_artifact.yaml")["model"]
    image = (
        environment.get("LLAMA_CPP_IMAGE")
        or load_yaml_mapping(root / "configs/recommended_images.yaml")["images"][
            "llama_cpp"
        ]["default"]
    )
    if not is_immutable_image_ref(image):
        raise ValueError("LLAMA_CPP_IMAGE must be an immutable image reference")
    override = document["profiles"][profile_id].get("runtime", {})
    runtime = {**document["runtime"], **override}
    return MainModelProfile(
        profile_id=profile_id,
        display_name=profile.display_name,
        model_id=artifact["repo_id"],
        revision=artifact["revision"],
        served_model_name=serving.public_model,
        command=cpu_runtime_command(root, port=port, profile_id=profile_id),
        compatibility=profile.compatibility,
        qualification=profile.qualification,
        capabilities={"deployed_input": list(profile.deployed_input)},
        gateway_policy=profile.gateway_policy,
        image=image,
        runtime_backend="llama-cpp",
        resolved_engine_policy=CpuEnginePolicy(
            runtime["context_size"], runtime["parallel"]
        ),
    )
