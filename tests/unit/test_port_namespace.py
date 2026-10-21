"""프로젝트 포트 대역 변경의 Offset 및 외부 엔진 격리 계약."""
import pytest
import yaml

from scripts.config import ports

from scripts.config.ports import REQUIRED_OFFSETS, assert_base, env_changes, managed_path, port_mapping, read_policy, replace_ports, ROOT


def test_repository_port_namespace():
    base, offsets = read_policy(ROOT)
    assert base >= 1000 and base % 100 == 0
    assert offsets == REQUIRED_OFFSETS


def test_port_namespace_mapping_and_bounds():
    m = port_mapping(9600, 9700, REQUIRED_OFFSETS)
    assert m[9600] == 9700
    assert m[9603] == 9703
    assert m[9610] == 9710
    assert m[9680] == 9780
    for invalid in (0, 9601, -100, 65500):
        with pytest.raises(ValueError):
            assert_base(invalid)


def test_dcgm_upstream_remains_unchanged():
    m = port_mapping(9600, 9700, REQUIRED_OFFSETS)
    src = "  - dcgm-exporter:9400\n  - gateway:9600\n"
    assert replace_ports(src, m, "ops/prometheus/prometheus.yml") == "  - dcgm-exporter:9400\n  - gateway:9700\n"


def test_env_migration_and_custom_port_safety():
    assert env_changes("GATEWAY_PORT=9400\nGRAFANA_PORT=9411\nAPI_KEYS=token\n", 9600, 9600) == (
        "GATEWAY_PORT=9600\nGRAFANA_PORT=9610\nAPI_KEYS=token\n"
    )
    assert env_changes("GATEWAY_PORT=9600\nGRAFANA_PORT=9610\n", 9600, 9700) == (
        "GATEWAY_PORT=9700\nGRAFANA_PORT=9710\n"
    )
    with pytest.raises(ValueError, match="운영자 지정 포트"):
        env_changes("GATEWAY_PORT=18080\n", 9600, 9700)


def test_port_namespace_tests_are_not_rewritten_when_changing_base():
    assert not managed_path("tests/unit/test_port_namespace.py")
    assert managed_path("configs/services.yaml")


def test_dcgm_table_port_remains_upstream_when_reusing_original_94xx_base():
    mapping = port_mapping(9400, 9600, REQUIRED_OFFSETS)
    docs = {
        "docs/04_runtime_modes.md": "| `dcgm-exporter` | `9400` | GPU metrics |\n",
        "docs/appendix.md": "| DCGM Exporter | `dcgm-exporter` | `9400` | - | GPU |\n",
        "docs/03_system_components.md": "| **DCGM Exporter** | `9400` | GPU telemetry |\n",
    }
    for path, original in docs.items():
        assert replace_ports(original, mapping, path) == original


def test_legacy_94xx_env_can_migrate_directly_to_any_selected_base():
    original = ("GATEWAY_PORT=9400\nGRAFANA_PORT=9411\n"
                "MAIN_MODEL_BASE_URL=http://main-llm-vllm:9401/v1\n"
                "EMBEDDING_KO_BASE_URL=http://embedding-ko-vllm:9406/v1\n"
                "PROMPT_INJECTION_DETECTOR_BASE_URL=http://prompt-injection-detector-runtime:9403/v1\n"
                "OUTSIDE_URL=https://outside.example:9400/api\n")
    changed = env_changes(original, 9600, 9700)
    assert "GATEWAY_PORT=9700" in changed
    assert "GRAFANA_PORT=9710" in changed
    assert "main-llm-vllm:9701" in changed
    assert "embedding-ko-vllm:9703" in changed
    assert "prompt-injection-detector-runtime:9704" in changed
    assert "OUTSIDE_URL=https://outside.example:9400/api" in changed


def test_env_preserves_nondefault_override_and_quotes():
    with pytest.raises(ValueError, match="운영자 지정 포트"):
        env_changes("GATEWAY_PORT=18080\n", 9600, 9700)


def test_noop_keeps_operator_host_port_override():
    assert env_changes("GATEWAY_PORT=18080\n", 9600, 9600) == "GATEWAY_PORT=18080\n"
    with pytest.raises(ValueError, match="정수 포트"):
        env_changes("GATEWAY_PORT=oops\n", 9600, 9700)


def test_single_command_changes_namespace_idempotently_and_restores(tmp_path, monkeypatch):
    # 전체 저장소를 변형하지 않고 서비스 레지스트리만 복사한 격리된 fixture에서 검증한다.
    target_config = tmp_path / "configs"
    target_config.mkdir()
    (target_config / "services.yaml").write_bytes((ROOT / "configs/services.yaml").read_bytes())
    current_base, _ = ports.read_policy(tmp_path)
    new_base = current_base + 100 if current_base < 65000 else current_base - 100
    monkeypatch.setattr(ports, "tracked_paths", lambda root: ["configs/services.yaml"])
    monkeypatch.setattr(ports, "preflight_bind", lambda *args: [])
    env_path = tmp_path / ".env"
    env_path.write_text("GATEWAY_PORT=9400\nGRAFANA_PORT=9411\n", encoding="utf-8")
    assert ports.run(tmp_path, new_base, yes=True, validate=False) == 0
    assert ports.read_policy(tmp_path)[0] == new_base
    assert f"GATEWAY_PORT={new_base}" in env_path.read_text(encoding="utf-8")
    first_env = env_path.read_bytes()
    assert ports.run(tmp_path, new_base, yes=True, validate=False) == 0
    assert env_path.read_bytes() == first_env
    assert ports.run(tmp_path, current_base, yes=True, validate=False) == 0
    assert ports.read_policy(tmp_path)[0] == current_base


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


def test_read_policy_rejects_drift_in_monitoring_and_nginx(tmp_path):
    for filename in ("configs/services.yaml", "configs/monitoring.yaml", "ops/access/team-api.nginx.conf"):
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / filename).read_bytes())
    base, offsets = read_policy(tmp_path)
    assert base >= 1024
    assert offsets == REQUIRED_OFFSETS

    monitoring_path = tmp_path / "configs/monitoring.yaml"
    current = yaml.safe_load(monitoring_path.read_text(encoding="utf-8"))
    current["monitoring_stack"]["mlx_metrics_exporter"]["internal_port"] += 1
    monitoring_path.write_text(yaml.safe_dump(current), encoding="utf-8")
    with pytest.raises(ValueError, match="MLX Metrics"):
        read_policy(tmp_path)
    monitoring_path.write_bytes((ROOT / "configs/monitoring.yaml").read_bytes())

    proxy = tmp_path / "ops/access/team-api.nginx.conf"
    original = proxy.read_text(encoding="utf-8")
    wrong_listener = original.replace(f"listen 127.0.0.1:{base + offsets['team_api_proxy']};", "listen 127.0.0.1:9999;")
    assert wrong_listener != original
    proxy.write_text(wrong_listener, encoding="utf-8")
    with pytest.raises(ValueError, match="Nginx 팀원 Listener"):
        read_policy(tmp_path)
