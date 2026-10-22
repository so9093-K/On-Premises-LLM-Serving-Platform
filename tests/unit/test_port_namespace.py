"""포트 대역은 배포 입력이며 역할별 offset과 외부 엔진 포트의 경계를 보호한다."""
from pathlib import Path

import pytest

from ai_model_serving.port_namespace import load_port_namespace
from scripts.config import port_runtime

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("base", [1100, 9400, 9600, 65400])
def test_namespace_projects_roles_from_one_base(base):
    namespace = load_port_namespace(ROOT, {"PLATFORM_PORT_BASE": str(base)})
    assert namespace.port("gateway") == base
    assert namespace.port("main_llm_vllm") == base + 1
    assert namespace.port("embedding_vllm") == base + 2
    assert namespace.port("risk_signal_service") == base + 5
    assert namespace.host_port("grafana", {}) == base + 10
    variables = namespace.compose_variables({})
    assert variables["PLATFORM_PORT_MAIN_LLM"] == str(base + 1)
    assert variables["GATEWAY_PORT"] == str(base)


@pytest.mark.parametrize("value", ["0", "-100", "9601", "65500", "oops"])
def test_invalid_base_fails_before_projection(value):
    with pytest.raises(ValueError):
        load_port_namespace(ROOT, {"PLATFORM_PORT_BASE": value})


def test_host_override_is_independent_of_internal_runtime_port():
    namespace = load_port_namespace(ROOT, {"PLATFORM_PORT_BASE": "9600"})
    assert namespace.host_port("gateway", {"GATEWAY_PORT": "18080"}) == 18080
    assert namespace.port("gateway") == 9600
    for value in ("0", "65536", "not-a-port"):
        with pytest.raises(ValueError):
            namespace.host_port("gateway", {"GATEWAY_PORT": value})


def test_url_projection_changes_authority_only():
    namespace = load_port_namespace(ROOT, {"PLATFORM_PORT_BASE": "9600"})
    assert namespace.translate_url("http://main-llm-vllm:9401/v1/9401?port=9401") == (
        "http://main-llm-vllm:9601/v1/9401?port=9401"
    )
    assert namespace.managed_role("outside.example") is None
    assert namespace.managed_role("main-llm-vllm") == "main_llm_vllm"


def test_metal_monitoring_and_upstream_ports_are_separate():
    namespace = load_port_namespace(ROOT, {"PLATFORM_PORT_BASE": "9600"})
    document = port_runtime.prometheus_document(namespace, "macos-metal")
    jobs = {item["job_name"]: item for item in document["scrape_configs"]}
    assert jobs["gateway"]["static_configs"][0]["targets"] == ["gateway:9600"]
    assert jobs["mlx-runtime"]["static_configs"][0]["targets"] == ["mlx-metrics-exporter:9616"]


def test_documentation_does_not_publish_internal_only_services():
    # 외부 제품의 내부 포트와 Compose Host publish 여부를 혼동하면 운영자가 방화벽을 잘못 열 수 있다.
    components = (ROOT / "docs/03_system_components.md").read_text(encoding="utf-8")
    appendix = (ROOT / "docs/appendix.md").read_text(encoding="utf-8")
    assert "| **DCGM Exporter** | `9400` |" in components
    for row in (
        "| Main Model Runtime | `main-llm-vllm` |",
        "| Korean Embedding Runtime | `embedding-ko-vllm` |",
        "| Prompt Injection Detector Runtime | `prompt-injection-detector-runtime` |",
        "| Prometheus | `prometheus` |",
        "| DCGM Exporter | `dcgm-exporter` |",
    ):
        actual = next(line for line in appendix.splitlines() if line.startswith(row))
        assert actual.split("|")[4].strip() == "-", actual
