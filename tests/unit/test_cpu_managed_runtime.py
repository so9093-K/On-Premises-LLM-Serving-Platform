"""관리형 CPU의 모델 무결성·Runtime 소유권 회귀 검증."""
import hashlib
import os
import shutil
import shlex
import subprocess
from pathlib import Path

import yaml
import pytest

from ai_model_serving.deployment_target import load_deployment_target
from ai_model_serving.serving_profile import load_main_serving_catalog
from ai_model_serving.main_model.cpu import cpu_runtime_command

ROOT = Path(__file__).resolve().parents[2]


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

    from ai_model_serving.settings import load_settings
    from unittest.mock import patch
    with patch.dict("os.environ", {
        "DEPLOYMENT_TARGET": "linux-cpu-managed",
        "MAIN_MODEL_STATIC_PROFILE": "cpu-gguf-text",
    }):
        settings = load_settings(root=ROOT, env_file=ROOT / ".nonexistent-cpu-model-env")
    assert settings.runtime_service_id("main_llm") == "cpu_main_llama"
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
    command = cpu_runtime_command(ROOT)
    assert command[command.index("--n-gpu-layers") + 1] == "0"
    assert any(str(v).endswith("/models:ro") for v in runtime["volumes"])


def test_managed_cpu_compose_resolves_all_services_without_gpu(tmp_path) -> None:
    """GPU가 없는 CI에서도 실제 Compose merge/interpolation 오류를 검출한다."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is unavailable")
    version = subprocess.run(
        ["docker", "compose", "version"],
        text=True, capture_output=True, check=False, timeout=15,
    )
    if version.returncode != 0:
        pytest.skip("Docker Compose plugin is unavailable")
    gateway_env = tmp_path / "gateway.env"
    risk_env = tmp_path / "risk.env"
    gateway_env.write_text("DEPLOYMENT_TARGET=linux-cpu-managed\n", encoding="utf-8")
    risk_env.write_text("DEPLOYMENT_TARGET=linux-cpu-managed\n", encoding="utf-8")
    env = {
        **os.environ,
        "GATEWAY_RUNTIME_ENV_FILE": str(gateway_env),
        "RISK_SIGNAL_SERVICE_RUNTIME_ENV_FILE": str(risk_env),
        "PLATFORM_IMAGE": "ai-model-serving-platform:test",
        "DEPLOYMENT_TARGET": "linux-cpu-managed",
        "CPU_MAIN_COMMAND": shlex.join(cpu_runtime_command(ROOT)),
        "CPU_MEMORY_LIMIT_BYTES": "4294967296",
    }
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-cpu-managed")
    command = ["docker", "compose", "--project-name", "cpu-compose-contract"]
    for filename in target.compose_files:
        command.extend(["-f", str(ROOT / filename)])
    command.extend(["--env-file", str(ROOT / ".env.compose.example"), "config", "--quiet"])
    result = subprocess.run(
        command, cwd=ROOT, env=env, text=True,
        capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_cpu_model_artifact_is_immutable() -> None:
    config = yaml.safe_load((ROOT / "configs/cpu_model_artifact.yaml").read_text(encoding="utf-8"))
    assert len(config["model"]["revision"]) == 40
    assert len(config["model"]["sha256"]) == 64
    images = yaml.safe_load((ROOT / "configs/recommended_images.yaml").read_text(encoding="utf-8"))
    assert "@sha256:" in images["images"]["llama_cpp"]["default"]


def test_cpu_control_mode_is_accepted_in_public_schemas() -> None:
    bootstrap = yaml.safe_load(
        (ROOT / "specs/schemas/control_plane_bootstrap_response.schema.json").read_text(encoding="utf-8")
    )
    envelope = yaml.safe_load(
        (ROOT / "specs/schemas/serving_envelope_response.schema.json").read_text(encoding="utf-8")
    )
    assert "managed_cpu" in bootstrap["properties"]["deployment"]["properties"]["control_mode"]["enum"]
    assert "managed_cpu" in envelope["properties"]["control_mode"]["enum"]


def test_managed_cpu_readiness_requires_the_expected_model_identity() -> None:
    from ai_model_serving.api.routers.gateway_ops import _managed_cpu_model_readiness

    assert _managed_cpu_model_readiness(
        {"data": [{"id": "local-main", "meta": {}}]}, "local-main"
    ) == ("ready", None)
    assert _managed_cpu_model_readiness(
        {"data": [{"id": "unrelated-model"}]}, "local-main"
    ) == ("not_ready", "CPU_MODEL_ID_MISMATCH")
    assert _managed_cpu_model_readiness(
        {"data": [{"id": "local-main", "meta": None}]}, "local-main"
    ) == ("not_ready", "CPU_MODEL_ID_MISMATCH")
    assert _managed_cpu_model_readiness({"data": []}, "local-main") == (
        "not_ready", "CPU_MODEL_ID_MISMATCH"
    )


def test_managed_cpu_model_listing_tracks_runtime_availability(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from ai_model_serving.apps.gateway import create_gateway_app
    from ai_model_serving.errors import ServiceError
    from ai_model_serving.settings import load_settings
    from ai_model_serving.upstream import RuntimeClient

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-cpu-managed")
    monkeypatch.setenv("MAIN_MODEL_STATIC_PROFILE", "cpu-gguf-text")
    settings = load_settings(root=ROOT, env_file=ROOT / ".nonexistent-cpu-model-env")
    app = create_gateway_app(settings)
    observations = [None, "wrong-model", "loading", "local-main"]

    async def observed_models(self, path, *, headers=None):
        assert path == "models"
        selected = observations.pop(0)
        if selected is None:
            raise ServiceError("MODEL_UNAVAILABLE", "CPU model is loading")
        return {
            "object": "list",
            "data": [{"id": "local-main", "meta": None}] if selected == "loading"
                    else [{"id": selected, "meta": {}}],
        }

    monkeypatch.setattr(RuntimeClient, "probe_json", observed_models)
    with TestClient(app) as client:
        for expected in ([], [], [], ["local-main"]):
            response = client.get("/v1/models")
            assert response.status_code == 200
            available = [item["id"] for item in response.json()["data"]]
            assert available == expected


def test_cpu_model_prepare_rechecks_ram_even_with_valid_cache(tmp_path, monkeypatch) -> None:
    from ai_model_serving.main_model import cpu as module
    model = tmp_path / "pinned.gguf"
    model.write_bytes(b"cached")
    (tmp_path / "configs").mkdir()
    manifest = tmp_path / "configs/cpu_model_artifact.yaml"
    manifest.write_text(yaml.safe_dump({
        "model": {
            "repo_id": "example/test",
            "revision": "a" * 40,
            "filename": model.name,
            "sha256": hashlib.sha256(b"cached").hexdigest(),
        },
        "runtime": {"minimum_available_ram_mib": 4096, "minimum_free_disk_mib": 2048},
    }), encoding="utf-8")
    monkeypatch.setattr(module, "available_memory_mib", lambda: 1024)
    with pytest.raises(RuntimeError, match="CPU RAM admission blocked"):
        module.prepare_cpu_model(config_root=tmp_path, output_root=tmp_path)


def test_cpu_model_prepare_checks_cached_bytes(tmp_path) -> None:
    from ai_model_serving.main_model import cpu as module
    file = tmp_path / "model.gguf"
    file.write_bytes(b"test")
    assert not module._check_sha256(file, "0" * 64)
    assert module._check_sha256(file, hashlib.sha256(b"test").hexdigest())
