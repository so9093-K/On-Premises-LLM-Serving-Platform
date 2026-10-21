"""프로젝트 포트 대역 변경의 Offset 및 외부 엔진 격리 계약."""
import pytest

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
        "docs/appendix.md": "| DCGM Exporter | `dcgm-exporter` | `9400` | `9412` | GPU |\n",
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
