#!/usr/bin/env python3
"""고정 Revision과 SHA-256으로 CPU GGUF Artifact를 준비한다."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import yaml

from ..project_paths import resolve_project_root
from ..host_resource_probe import available_memory_mib


def _check_sha256(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def prepare_cpu_model(
    *, config_root: Path | None = None, output_root: Path | None = None
) -> Path:
    from huggingface_hub import hf_hub_download

    root = config_root or resolve_project_root()
    output_root = output_root or root / ".runtime/cpu-models"
    manifest = yaml.safe_load(
        (root / "configs/cpu_model_artifact.yaml").read_text(encoding="utf-8")
    )
    model = manifest["model"]
    policy = manifest["runtime"]
    filename = str(model["filename"])
    revision = str(model["revision"])
    sha256 = str(model["sha256"]).lower()
    if Path(filename).name != filename or not filename.endswith(".gguf"):
        raise RuntimeError("CPU GGUF filename must be a single basename")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise RuntimeError("CPU model revision must be a full immutable SHA")
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise RuntimeError("CPU model checksum must be SHA-256")
    # Artifact가 캐시에 있어도 모델 적재에 필요한 RAM은 매번 확인해야 한다.
    available = available_memory_mib()
    minimum_ram = int(policy["minimum_available_ram_mib"])
    if available is None or available < minimum_ram:
        raise RuntimeError(
            f"CPU RAM admission blocked: available={available}MiB, required={minimum_ram}MiB"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / filename
    if output.is_file() and not output.is_symlink() and _check_sha256(output, sha256):
        print(f"[cpu-model] verified cached artifact: {output}")
        return output
    free = shutil.disk_usage(output_root).free // (1024 * 1024)
    minimum_disk = int(policy["minimum_free_disk_mib"])
    if free < minimum_disk:
        raise RuntimeError(
            f"CPU cache disk admission blocked: free={free}MiB, required={minimum_disk}MiB"
        )
    downloaded = Path(
        hf_hub_download(
            repo_id=str(model["repo_id"]),
            revision=revision,
            filename=filename,
            local_files_only=os.environ.get("CPU_MODEL_OFFLINE") == "1",
        )
    )
    if not _check_sha256(downloaded, sha256):
        raise RuntimeError("CPU model source checksum mismatch")
    descriptor, name = tempfile.mkstemp(
        prefix=".cpu-model.", suffix=".tmp", dir=output_root
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target, downloaded.open("rb") as src:
            shutil.copyfileobj(src, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if not _check_sha256(temporary, sha256):
            raise RuntimeError("CPU cache checksum verification failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[cpu-model] verified: {output}")
    return output


def cpu_runtime_command(
    config_root: Path, *, port: int | None = None, profile_id: str | None = None
) -> tuple[str, ...]:
    """CPU 명령은 프로필과 검증된 Artifact 선언에서만 생성한다."""
    from ..configuration import load_yaml_mapping

    catalog = load_yaml_mapping(config_root / "configs/cpu_main_model_profiles.yaml")
    artifact = load_yaml_mapping(config_root / "configs/cpu_model_artifact.yaml")[
        "model"
    ]
    selected_profile = profile_id or str(catalog["default_profile"])
    profiles = catalog["profiles"]
    if selected_profile not in profiles:
        raise ValueError(f"unknown CPU profile: {selected_profile}")
    override = profiles[selected_profile].get("runtime", {})
    if not isinstance(override, dict) or set(override) - {"context_size", "parallel", "threads"}:
        raise ValueError("invalid CPU profile runtime override")
    runtime = {**catalog["runtime"], **override}
    filename = str(artifact["filename"])
    if Path(filename).name != filename or not filename.endswith(".gguf"):
        raise ValueError("CPU model filename must be a GGUF basename")
    values = {key: runtime[key] for key in ("context_size", "parallel", "threads")}
    selected_port = runtime["port"] if port is None else port
    if any(type(v) is not int or v <= 0 for v in (*values.values(), selected_port)):
        raise ValueError("CPU runtime limits must be positive integers")
    if runtime.get("gpu_layers") != 0 or selected_port > 65535:
        raise ValueError("CPU runtime must use zero GPU layers and a valid port")
    return (
        "--model",
        "/models/" + filename,
        "--alias",
        str(catalog["public_model"]),
        "--host",
        "0.0.0.0",
        "--port",
        str(selected_port),
        "--ctx-size",
        str(values["context_size"]),
        "--parallel",
        str(values["parallel"]),
        "--threads",
        str(values["threads"]),
        "--n-gpu-layers",
        "0",
        "--reasoning",
        "off",
        # Prometheus가 CPU Main도 vLLM과 같은 /metrics 경로로 수집한다. 없으면 501로 down 표시된다.
        "--metrics",
    )
