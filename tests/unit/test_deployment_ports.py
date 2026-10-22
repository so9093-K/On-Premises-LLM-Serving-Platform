"""배포 포트 설정은 실행 주소·명령·관측에 반영되며 개발 소스를 변경하지 않는다."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_model_serving.main_model.boot import render_boot_override
from ai_model_serving.main_model.catalog import load_main_model_catalog
from ai_model_serving.port_namespace import load_port_namespace
from ai_model_serving.runtime_controller_config import load_runtime_controller_config
from ai_model_serving.runtime_topology import load_runtime_topology
from ai_model_serving.settings import load_settings
from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file
from scripts.config import ports, port_runtime, setup_env

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    monkeypatch.setattr(ports, "ROOT", tmp_path)
    monkeypatch.setattr(setup_env, "ROOT", tmp_path)
    monkeypatch.setattr(ports, "host_port_conflicts", lambda _: [])
    env = tmp_path / ".env"
    env.write_text(
        "# operator settings\nPLATFORM_PORT_BASE=9400\nBUILD_PROFILE=compose\n"
        "DEPLOYMENT_TARGET=linux-nvidia-dynamic\n"
        "GATEWAY_PORT=9400\nGRAFANA_PORT=9410\n"
        "MAIN_MODEL_BASE_URL=http://main-llm-vllm:9401/v1\n"
        "RISK_SIGNAL_SERVICE_BASE_URL=http://risk-signal-service:9405\n"
        "EXTERNAL_BASE_URL=http://outside.example:9400/v1\n"
        "API_KEYS=operator-secret-9400\nHF_TOKEN=operator-hf-token\n"
    )
    return env


def test_configuration_changes_without_git_node_tests_or_source_edits(deployment, monkeypatch):
    snapshot = {p.relative_to(deployment.parent): p.read_bytes() for p in deployment.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("설정 변경이 외부 개발 도구를 실행했다"))
    assert ports.change_port_base(deployment, 9600, plan_only=True) == 0
    assert deployment.read_bytes() == snapshot[Path(".env")]
    assert ports.change_port_base(deployment, 9600) == 0
    values = load_strict_env_file(deployment)
    assert values["PLATFORM_PORT_BASE"] == "9600"
    assert values["GATEWAY_PORT"] == "9600" and values["GRAFANA_PORT"] == "9610"
    assert values["MAIN_MODEL_BASE_URL"] == "http://main-llm-vllm:9601/v1"
    assert values["RISK_SIGNAL_SERVICE_BASE_URL"] == "http://risk-signal-service:9605"
    assert values["EXTERNAL_BASE_URL"] == "http://outside.example:9400/v1"
    assert values["API_KEYS"] == "operator-secret-9400" and values["HF_TOKEN"] == "operator-hf-token"
    assert deployment.read_text().startswith("# operator settings\n")
    for name, original in snapshot.items():
        if name != Path(".env"):
            assert (deployment.parent / name).read_bytes() == original
    after = deployment.read_bytes()
    assert ports.change_port_base(deployment, 9600) == 0
    assert deployment.read_bytes() == after
    assert ports.change_port_base(deployment, 9400) == 0
    assert load_strict_env_file(deployment)["MAIN_MODEL_BASE_URL"] == "http://main-llm-vllm:9401/v1"


def test_foreign_port_conflict_and_invalid_base_preserve_configuration(deployment, monkeypatch):
    before = deployment.read_bytes()
    monkeypatch.setattr(ports, "host_port_conflicts", lambda _: ["Gateway 9600: another checkout"])
    assert ports.change_port_base(deployment, 9600) == 2
    assert deployment.read_bytes() == before
    for base in (80, 9601, 65500):
        with pytest.raises(ValueError):
            ports.change_port_base(deployment, base)
        assert deployment.read_bytes() == before


def test_explicit_host_override_and_external_runtime_are_preserved(deployment):
    deployment.write_text(deployment.read_text().replace("GATEWAY_PORT=9400", "GATEWAY_PORT=18080")
                          .replace("http://main-llm-vllm:9401/v1", "http://outside.example:9401/v1"))
    assert ports.change_port_base(deployment, 9600) == 0
    values = load_strict_env_file(deployment)
    assert values["GATEWAY_PORT"] == "18080"
    assert values["MAIN_MODEL_BASE_URL"] == "http://outside.example:9401/v1"


def test_settings_catalog_controller_and_monitoring_use_one_base(tmp_path, monkeypatch):
    env_file = tmp_path / "app.env"
    env_file.write_text("PLATFORM_PORT_BASE=9600\nDEPLOYMENT_TARGET=linux-nvidia-dynamic\n")
    monkeypatch.delenv("PLATFORM_PORT_BASE", raising=False)
    settings = load_settings(ROOT, env_file=env_file)
    assert settings.runtime("main_llm").base_url == "http://main-llm-vllm:9601/v1"
    assert settings.risk_signal_service_endpoint.base_url == "http://risk-signal-service:9605"
    env = {**os.environ, "PLATFORM_PORT_BASE": "9600"}
    catalog = load_main_model_catalog(ROOT / "configs/main_model_profiles.yaml", env=env)
    assert catalog.runtime["container_port"] == 9601
    for profile in catalog.profiles.values():
        assert profile.command[profile.command.index("--port") + 1] == "9601"
    topology = load_runtime_topology(ROOT, environment=env)
    assert topology.health_url_by_service["embedding-vllm"] == "http://embedding-vllm:9602/health"
    controller = load_runtime_controller_config({**env, "APP_CONFIG_ROOT": str(ROOT)})
    assert controller.gateway_internal_url == "http://gateway:9600"
    namespace = load_port_namespace(ROOT, env)
    document = port_runtime.prometheus_document(namespace, "linux")
    jobs = {item["job_name"]: item for item in document["scrape_configs"]}
    assert jobs["gateway"]["static_configs"][0]["targets"] == ["gateway:9600"]
    assert jobs["risk-signal-service"]["static_configs"][0]["targets"] == ["risk-signal-service:9605"]
    assert jobs["dcgm-exporter"]["static_configs"][0]["targets"] == ["dcgm-exporter:9400"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI required for Compose parsing")
def test_effective_cpu_compose_has_consistent_runtime_ports(tmp_path):
    values = load_strict_env_file(ROOT / ".env.compose.example")
    values.update(PLATFORM_PORT_BASE="9600", GATEWAY_PORT="9600", GRAFANA_PORT="9610",
                  GRAFANA_ADMIN_PASSWORD="test-only", MAIN_MODEL_BOOT_PROFILE="gemma4-e4b-it")
    env_file = tmp_path / "compose.env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    _, document = render_boot_override(catalog_path=ROOT / "configs/main_model_profiles.yaml",
                                      state_path=tmp_path / "state.json", env_path=env_file, cpu_template=True)
    override = tmp_path / "boot.yaml"
    override.write_text(yaml.safe_dump(document))
    env = {**os.environ, **load_port_namespace(ROOT, values).compose_variables(values),
           "COMPOSE_SERVICE_ENV_FILE": str(env_file), "COMPOSE_CHECKOUT_ROOT": str(ROOT)}
    result = subprocess.run(["docker", "compose", "--env-file", str(env_file), "-f",
                             str(ROOT / "ops/compose/full-stack.private-network.yaml"),
                             "-f", str(override), "config", "--format", "json"],
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for service, port in (("gateway", 9600), ("risk-signal-service", 9605), ("main-llm-vllm", 9601)):
        command = services[service]["command"]
        assert command[command.index("--port") + 1] == str(port)
        healthcheck = str(services[service].get("healthcheck", {})) + str(services[service].get("environment", {}))
        assert str(port) in healthcheck
    assert services["gateway"]["ports"][0]["target"] == 9600
    assert services["gateway"]["ports"][0]["published"] == "9600"
    assert services["grafana"]["ports"][0]["target"] == 3000
    assert services["grafana"]["ports"][0]["published"] == "9610"
