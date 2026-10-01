from __future__ import annotations

from pathlib import Path

from ai_model_serving.access_profile import access_profile_env_values
from ai_model_serving.configuration import load_yaml_mapping
from ai_model_serving.host_exposure import host_published_service_ids


ROOT = Path(__file__).resolve().parents[2]


def test_operator_bind_policy_projects_only_current_host_boundary_binds() -> None:
    services = load_yaml_mapping(ROOT / "configs/services.yaml")["services"]
    host_bind_keys = {
        str(services[service_id]["host_env_bind"])
        for service_id in host_published_service_ids(services)
        if services[service_id].get("host_env_bind")
    }
    current = {
        key: f"192.0.2.{index}"
        for index, key in enumerate(sorted(host_bind_keys), start=10)
    }
    current["UNMANAGED_BIND_ADDR"] = "198.51.100.20"

    values = access_profile_env_values("private", current=current)
    projected_binds = {
        key: value for key, value in values.items() if key.endswith("_BIND_ADDR")
    }

    assert set(projected_binds) == host_bind_keys
    assert projected_binds == {key: current[key] for key in host_bind_keys}
