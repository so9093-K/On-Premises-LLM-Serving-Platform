"""관리형 CPU의 모델 무결성·Runtime 소유권 회귀 검증."""
import hashlib
import importlib.util
from pathlib import Path

import yaml

from ai_model_serving.deployment_target import load_deployment_target
from ai_model_serving.serving_profile import load_main_serving_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_cpu_managed_target_is_platform_owned() -> None:
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-cpu-managed")
    assert target.static_serving
    assert not target.controllable
    assert target.control_mode == "managed_cpu"
    assert target.lifecycle_owner == "platform"
    assert target.gateway_runtime_host == "cpu-main"
    assert target.supports("chat")
    assert target.runtime_backend == "llama-cpp"
    assert target.qualification_status == "unverified"
    catalog = load_main_serving_catalog(ROOT / target.main_profile_catalog)
    assert catalog.public_model == "local-main"


def test_cpu_compose_has_no_gpu_device_or_host_port() -> None:
    config = yaml.safe_load(
        (ROOT / "ops/compose/overrides/managed.cpu-main.yaml").read_text(encoding="utf-8")
    )
    runtime = config["services"]["cpu-main"]
    assert not runtime.get("ports")
    assert not runtime.get("devices")
    assert not runtime.get("deploy")
    assert "--n-gpu-layers" in runtime["command"]
    assert runtime["command"][runtime["command"].index("--n-gpu-layers") + 1] == "0"
    assert any(str(v).endswith("/models:ro") for v in runtime["volumes"])


def test_cpu_model_artifact_is_immutable() -> None:
    config = yaml.safe_load((ROOT / "configs/cpu_model_artifact.yaml").read_text(encoding="utf-8"))
    assert len(config["model"]["revision"]) == 40
    assert len(config["model"]["sha256"]) == 64
    images = yaml.safe_load((ROOT / "configs/recommended_images.yaml").read_text(encoding="utf-8"))
    assert "@sha256:" in images["images"]["llama_cpp"]["default"]


def test_cpu_model_prepare_checks_cached_bytes(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "cpu_artifact_prepare", ROOT / "scripts/models/prepare_cpu_model.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    file = tmp_path / "model.gguf"
    file.write_bytes(b"test")
    assert not module._check_sha256(file, "0" * 64)
    assert module._check_sha256(file, hashlib.sha256(b"test").hexdigest())
