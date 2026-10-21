"""GPU 모델 자원이 없는 배포의 계약을 보호한다."""
from pathlib import Path

from ai_model_serving.deployment_target import load_deployment_target

ROOT = Path(__file__).resolve().parents[2]


def test_core_target_does_not_require_model_runtime() -> None:
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-core")
    assert target.implementation_status == "implemented"
    assert target.runtime_backend == "none"
    assert target.main_profile_catalog is None
    assert not target.supports("chat")
    assert target.supports("risk")
    assert not target.supports("gpu_admission")
    assert target.control_mode == "static"
    assert target.compose_files


def test_cpu_static_target_has_explicit_external_lifecycle() -> None:
    from ai_model_serving.serving_profile import load_main_serving_catalog

    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-cpu-static")
    assert target.runtime_backend == "llama-cpp"
    assert target.supports("chat")
    assert not target.supports("gpu_admission")
    assert target.lifecycle_owner == "external"
    catalog = load_main_serving_catalog(ROOT / target.main_profile_catalog)
    assert catalog.public_model == "local-main"
    # 공통 Serving 프로필의 검증과 외부 Runtime 배포 Target의 검증은 별개다.
    assert target.qualification_status == "unverified"


def test_core_settings_do_not_require_main_profile(monkeypatch) -> None:
    from ai_model_serving.settings import load_settings

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-core")
    monkeypatch.delenv("MAIN_MODEL_STATIC_PROFILE", raising=False)
    settings = load_settings(root=ROOT, env_file=ROOT / ".nonexistent-core-env")
    assert "main_llm" not in settings.runtime_endpoints
    assert "main_llm" not in settings.required_runtime_keys
    assert settings.public_models == ()
    assert settings.risk_signal_service_endpoint is not None


def test_core_gateway_does_not_advertise_or_serve_missing_model(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from ai_model_serving.apps.gateway import create_gateway_app
    from ai_model_serving.settings import load_settings

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-core")
    monkeypatch.delenv("MAIN_MODEL_STATIC_PROFILE", raising=False)
    settings = load_settings(root=ROOT, env_file=ROOT / ".nonexistent-core-env")
    app = create_gateway_app(settings)
    with TestClient(app) as client:
        from jsonschema import Draft202012Validator
        from ai_model_serving.openapi_contracts import load_contract_schema

        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        listing = client.get("/v1/models")
        assert listing.status_code == 200
        assert listing.json() == {"object": "list", "data": []}
        Draft202012Validator(load_contract_schema("model_list_response.schema.json")).validate(listing.json())
        result = client.post("/v1/chat/completions", json={
            "model": "local-main",
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "max_tokens": 4,
        })
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_cpu_static_profile_loads_without_gpu(monkeypatch) -> None:
    from ai_model_serving.settings import load_settings

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-cpu-static")
    monkeypatch.setenv("MAIN_MODEL_STATIC_PROFILE", "cpu-gguf-text")
    monkeypatch.setenv("MAIN_MODEL_BASE_URL", "http://127.0.0.1:8080/v1")
    settings = load_settings(root=ROOT, env_file=ROOT / ".nonexistent-cpu-env")
    assert settings.static_main_engine_policy["gpu_layers"] == 0
    assert settings.runtime("main_llm").max_concurrency == 1
    assert any(item["id"] == "local-main" for item in settings.public_models)


def test_gpu_target_retains_existing_model_contract() -> None:
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-nvidia-dynamic")
    assert target.supports("chat")
    assert target.supports("gpu_admission")
    assert target.main_profile_catalog == "configs/main_model_profiles.yaml"
