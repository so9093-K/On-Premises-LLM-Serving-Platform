from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import yaml


class ResetList(list):
    """Compose가 상위 GPU 장치 목록을 병합하지 않고 비우도록 표시한다."""


yaml.SafeDumper.add_representer(
    ResetList, lambda dumper, value: dumper.represent_sequence("!reset", value)
)


class BootOverrideLoader(yaml.SafeLoader):
    pass


BootOverrideLoader.add_constructor(
    "!reset", lambda loader, node: loader.construct_sequence(node)
)

from .catalog import (
    resolve_boot_profile,
)
from .state import read_active_profile
from ..settings_parts.dotenv_parser import load_strict_env_file


def read_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"environment file not found: {path}")
    return load_strict_env_file(path)


def resolve_compose_relative_path(raw: str, compose_file: Path) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (compose_file.resolve().parent / raw.removeprefix("./")).resolve()


def _strict_bool(value: str, *, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{key} must be true or false, got: {value!r}")


def render_boot_override(
    *,
    catalog_path: Path,
    state_path: Path,
    env_path: Path,
    cpu_template: bool = False,
) -> tuple[str, dict[str, Any]]:
    env = read_env_values(env_path)
    from .managed_catalog import load_managed_catalog
    catalog = load_managed_catalog(catalog_path.resolve().parent.parent, env, cpu_available=cpu_template, catalog_path=catalog_path)
    configured = env.get("MAIN_MODEL_BOOT_PROFILE", catalog.default_profile)
    locked = _strict_bool(
        env.get("MAIN_MODEL_PROFILE_LOCKED", "false"),
        key="MAIN_MODEL_PROFILE_LOCKED",
    )
    profile_id = "cpu-gguf-text" if cpu_template else resolve_boot_profile(
        catalog,
        configured_profile=configured,
        locked=locked,
        persisted_profile=read_active_profile(state_path),
    )
    profile = catalog.profiles[profile_id]
    override = {
        "services": {
            str(catalog.runtime["compose_service"]): {
                # 이 프로필에 대해 resolve된 image로 boot한다 (프로필이 자체
                # runtime을 고정할 수 있다, 예: audio-capable 빌드). loader가
                # profile.image가 registry digest 또는 local Docker image ID로
                # 고정됐으며 비어있지 않음을 loader가 보장한다.
                "image": str(profile.image),
                "command": list(profile.command),
            }
        }
    }

    if profile.runtime_backend == "llama-cpp":
        service = override["services"][str(catalog.runtime["compose_service"])]
        root = catalog_path.resolve().parent.parent
        # 초기 Compose의 장치 정책을 보존해 CPU 기동 뒤 GPU 복귀에도 사용한다.
        source = yaml.safe_load(
            (root / "ops/compose/full-stack.private-network.yaml").read_text()
        )
        devices = source["services"][str(catalog.runtime["compose_service"])]["deploy"][
            "resources"
        ]["reservations"]["devices"]
        requests = [
            {
                "Driver": d.get("driver", ""),
                "Count": 0
                if "device_ids" in d
                else -1
                if d.get("count", "all") == "all"
                else int(d["count"]),
                "Capabilities": [d["capabilities"]],
                **({"DeviceIDs": d["device_ids"]} if "device_ids" in d else {}),
            }
            for d in devices
        ]
        service.update(
            mem_limit=catalog.runtime["cpu_memory_limit_bytes"],
            memswap_limit=catalog.runtime["cpu_memory_limit_bytes"],
            pids_limit=256,
            labels={
                "ai_model_serving.gpu_device_requests": json.dumps(requests),
                "ai_model_serving.runtime_backend": "llama-cpp",
            },
            deploy={"resources": {"reservations": {"devices": ResetList()}}},
        )
    return profile_id, override
