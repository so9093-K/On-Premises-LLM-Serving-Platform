from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.qualification.status_eligibility import eligible_qualified_run_ids


def _profiles() -> dict:
    return {
        "profiles": {
            "gemma-test": {
                "model_id": "org/model",
                "revision": "a" * 40,
                "qualification": {"status": "unverified"},
                "capabilities": {"deployed_input": ["text", "image"]},
            }
        }
    }


def _targets() -> dict:
    return {
        "targets": {
            "linux-nvidia-dynamic": {
                "main_profile_catalog": "configs/main_model_profiles.yaml"
            },
            "linux-nvidia-static": {
                "main_profile_catalog": "configs/main_model_profiles.yaml"
            },
            "macos-metal-static": {
                "main_profile_catalog": "configs/macos_mlx_runtime.yaml"
            },
        }
    }


def _record(
    record_id: str,
    *,
    target: str,
    resource_variant: str | None = None,
) -> tuple[str, dict]:
    subject = {
        "type": "main_model_profile",
        "profile_id": "gemma-test",
        "model_id": "org/model",
        "revision": "a" * 40,
    }
    if resource_variant is not None:
        subject["resource_variant"] = resource_variant
    return record_id, {
        "kind": "qualified_run",
        "subject": subject,
        "deployment_target": target,
        "capabilities": ["text", "image"],
        "result": "passed",
    }


def test_promotion_uses_only_evidence_from_the_reviewed_deployment_target() -> None:
    linux_id, linux = _record(
        "linux-run",
        target="linux-nvidia-dynamic",
        resource_variant="rtx4090-24gb",
    )
    static_id, static = _record(
        "static-run",
        target="linux-nvidia-static",
    )
    evidence = {"records": {linux_id: linux, static_id: static}}

    with patch(
        "scripts.qualification.status_eligibility.validate_qualification_evidence_document"
    ):
        eligible = eligible_qualified_run_ids(
            "gemma-test",
            "linux-nvidia-dynamic",
            evidence,
            _profiles(),
            _targets(),
            {},
        )

    assert eligible == ["linux-run"]


def test_resource_variant_is_provenance_not_profile_promotion_gate() -> None:
    reference_id, reference = _record(
        "reference-run",
        target="linux-nvidia-dynamic",
    )
    override_id, override = _record(
        "override-run",
        target="linux-nvidia-dynamic",
        resource_variant="rtx4090-24gb",
    )
    evidence = {"records": {reference_id: reference, override_id: override}}

    with patch(
        "scripts.qualification.status_eligibility.validate_qualification_evidence_document"
    ):
        eligible = eligible_qualified_run_ids(
            "gemma-test",
            "linux-nvidia-dynamic",
            evidence,
            _profiles(),
            _targets(),
            {},
        )

    assert eligible == ["override-run", "reference-run"]


def test_promotion_refuses_target_owned_by_a_different_main_profile_catalog() -> None:
    run_id, record = _record(
        "mac-run",
        target="macos-metal-static",
    )

    with patch(
        "scripts.qualification.status_eligibility.validate_qualification_evidence_document"
    ):
        with pytest.raises(SystemExit, match="does not use configs/main_model_profiles.yaml"):
            eligible_qualified_run_ids(
                "gemma-test",
                "macos-metal-static",
                {"records": {run_id: record}},
                _profiles(),
                _targets(),
                {},
            )
