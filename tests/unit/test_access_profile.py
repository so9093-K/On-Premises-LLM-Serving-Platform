from __future__ import annotations

from ai_model_serving.access_profile import access_profile_env_values


def test_operator_bind_policy_preserves_only_host_boundary_binds() -> None:
    values = access_profile_env_values(
        "private",
        current={
            "GATEWAY_BIND_ADDR": "192.168.10.20",
            "GRAFANA_BIND_ADDR": "192.168.10.21",
            "MAIN_MODEL_VLLM_BIND_ADDR": "192.168.10.25",
        },
    )

    assert values["GATEWAY_BIND_ADDR"] == "192.168.10.20"
    assert values["GRAFANA_BIND_ADDR"] == "192.168.10.21"
    assert "MAIN_MODEL_VLLM_BIND_ADDR" not in values
    assert "RISK_SIGNAL_SERVICE_BIND_ADDR" not in values
    assert "PROMETHEUS_BIND_ADDR" not in values
    assert "EXPOSURE_MODE" not in values
