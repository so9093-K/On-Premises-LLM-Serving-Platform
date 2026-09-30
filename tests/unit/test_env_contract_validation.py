from __future__ import annotations

from scripts.validation.validate_env_contract import (
    _commented_assignment_keys,
    validate_service_env_projections,
)


def test_commented_assignment_exposes_removed_env_surface(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(
        "# MAX_REQUEST_BODY_BYTES=<bytes>\n"
        "# MAX_REQUEST_BODY_BYTES is owned by model_serving.yaml\n",
        encoding="utf-8",
    )

    assert _commented_assignment_keys(example) == {"MAX_REQUEST_BODY_BYTES"}


def test_service_projection_rejects_removed_persistent_key(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "deployment_targets.yaml").write_text(
        "targets:\n"
        "  static-target:\n"
        "    internal_service_token_required: false\n",
        encoding="utf-8",
    )
    contract = {
        "removed_keys": {"MAX_REQUEST_BODY_BYTES": "model_serving.yaml owns it"},
        "service_env_projections": {
            "static_gateway": {
                "service": "gateway",
                "deployment_targets": ["static-target"],
                "required_source_keys": ["DEPLOYMENT_TARGET"],
                "runtime_keys": ["DEPLOYMENT_TARGET", "MAX_REQUEST_BODY_BYTES"],
            }
        },
    }

    violations = validate_service_env_projections(tmp_path, contract)

    assert any(
        "runtime_keys contains removed persistent key(s): MAX_REQUEST_BODY_BYTES" in violation
        for violation in violations
    )


def test_service_projection_requires_every_static_runtime_env_consumer(tmp_path):
    configs = tmp_path / "configs"
    compose = tmp_path / "ops" / "compose"
    configs.mkdir()
    compose.mkdir(parents=True)
    (configs / "deployment_targets.yaml").write_text(
        "targets:\n"
        "  static-target:\n"
        "    internal_service_token_required: true\n"
        "    compose_files:\n"
        "      - ops/compose/static.yaml\n",
        encoding="utf-8",
    )
    (configs / "services.yaml").write_text(
        "services:\n"
        "  gateway:\n"
        "    compose_service: gateway\n"
        "  risk_signal_service:\n"
        "    compose_service: risk-signal-service\n",
        encoding="utf-8",
    )
    (compose / "static.yaml").write_text(
        "services:\n"
        "  gateway:\n"
        "    env_file: ${GATEWAY_RUNTIME_ENV_FILE}\n"
        "  risk-signal-service:\n"
        "    env_file: ${RISK_SIGNAL_SERVICE_RUNTIME_ENV_FILE}\n",
        encoding="utf-8",
    )
    contract = {
        "service_env_projections": {
            "static_gateway": {
                "service": "gateway",
                "deployment_targets": ["static-target"],
                "required_source_keys": ["DEPLOYMENT_TARGET"],
                "runtime_keys": ["DEPLOYMENT_TARGET"],
            }
        }
    }

    violations = validate_service_env_projections(tmp_path, contract)

    assert (
        "env_contract.yaml: missing service env projection for "
        "target 'static-target' and service 'risk_signal_service'"
    ) in violations
