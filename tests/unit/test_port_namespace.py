"""프로젝트 포트 대역 변경의 Offset 및 외부 엔진 격리 계약."""
import pytest

from scripts.config.ports import REQUIRED_OFFSETS, assert_base, env_changes, port_mapping, read_policy, replace_ports, ROOT


def test_repository_port_namespace():
    assert read_policy(ROOT) == (9600, REQUIRED_OFFSETS)


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
