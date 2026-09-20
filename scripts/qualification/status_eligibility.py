#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validation.governance.common import read_yaml  # noqa: E402
from scripts.validation.governance.qualification import (  # noqa: E402
    load_qualification_check_contract,
    qualification_record_matches_current_profile,
    validate_qualification_evidence_document,
)


def eligible_qualified_run_ids(
    profile_id: str,
    deployment_target: str,
    evidence_document: object,
    profiles_document: object,
    deployment_targets_document: object,
    qualification_checks_document: object,
) -> list[str]:
    """Return qualified_run evidence eligible for promotion on one deployment target.

    resource_variant는 evidence provenance지만 profile-level qualification promotion의
    gate가 아니다. 같은 profile contract를 현재 deployment target에서 검증한
    qualified_run이면 reference/override resource policy 차이만으로 배제하지 않는다.
    """
    validate_qualification_evidence_document(
        evidence_document,
        profiles_document,
        deployment_targets_document,
        qualification_checks_document,
    )

    target_id = str(deployment_target or "").strip()
    if not target_id:
        raise SystemExit("deployment target must be non-empty for status promotion")
    if not isinstance(deployment_targets_document, dict):
        raise SystemExit("deployment_targets.yaml must be a mapping")
    targets = deployment_targets_document.get("targets")
    if not isinstance(targets, dict) or target_id not in targets:
        raise SystemExit(f"unknown deployment target {target_id!r}")
    target = targets[target_id]
    if not isinstance(target, dict):
        raise SystemExit(f"deployment target {target_id!r} must be a mapping")
    if target.get("main_profile_catalog") != "configs/main_model_profiles.yaml":
        raise SystemExit(
            f"deployment target {target_id!r} does not use configs/main_model_profiles.yaml"
        )

    if not isinstance(profiles_document, dict):
        raise SystemExit("main_model_profiles.yaml must be a mapping")
    profiles = profiles_document.get("profiles")
    if not isinstance(profiles, dict) or profile_id not in profiles:
        raise SystemExit(f"unknown main model profile {profile_id!r}")
    profile = profiles[profile_id]
    if not isinstance(profile, dict):
        raise SystemExit(f"main model profile {profile_id!r} must be a mapping")

    qualification = profile.get("qualification")
    if not isinstance(qualification, dict) or qualification.get("status") != "unverified":
        raise SystemExit(
            f"main model profile {profile_id!r} must currently be unverified for promotion"
        )

    capabilities = profile.get("capabilities")
    deployed_input = (
        capabilities.get("deployed_input") if isinstance(capabilities, dict) else None
    )
    if not isinstance(deployed_input, list) or not deployed_input:
        raise SystemExit(
            f"main model profile {profile_id!r} must declare deployed_input capabilities"
        )

    if not isinstance(evidence_document, dict):
        raise SystemExit("qualification_evidence.yaml must be a mapping")
    records = evidence_document.get("records")
    if not isinstance(records, dict):
        raise SystemExit("qualification_evidence.yaml must declare records")

    expected_model_id = str(profile.get("model_id", ""))
    expected_revision = str(profile.get("revision", ""))
    expected_capabilities = set(str(item) for item in deployed_input)
    _, capability_requirements = load_qualification_check_contract(
        qualification_checks_document
    )
    matches: list[str] = []
    for record_id, raw_record in records.items():
        if not isinstance(raw_record, dict):
            continue
        if raw_record.get("kind") != "qualified_run":
            continue
        if qualification_record_matches_current_profile(
            raw_record,
            profile_id=profile_id,
            model_id=expected_model_id,
            revision=expected_revision,
            capabilities=expected_capabilities,
            eligible_targets={target_id},
            capability_requirements=capability_requirements,
        ):
            matches.append(str(record_id))

    if not matches:
        raise SystemExit(
            f"main model profile {profile_id!r} has no current qualified_run "
            f"eligible for verified promotion on deployment target {target_id!r}"
        )
    return sorted(matches)


def check_profile(profile_id: str, deployment_target: str) -> dict[str, Any]:
    evidence = read_yaml("configs/qualification_evidence.yaml")
    profiles = read_yaml("configs/main_model_profiles.yaml")
    targets = read_yaml("configs/deployment_targets.yaml")
    checks = read_yaml("configs/qualification_checks.yaml")
    record_ids = eligible_qualified_run_ids(
        profile_id, deployment_target, evidence, profiles, targets, checks
    )
    return {
        "profile_id": profile_id,
        "deployment_target": deployment_target,
        "eligible": True,
        "qualified_run_ids": record_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check ADR-0033 eligibility for an explicit unverified-to-verified "
            "profile promotion."
        )
    )
    parser.add_argument("--profile", required=True, help="Main Model profile id")
    parser.add_argument("--target", required=True, help="Deployment target id")
    args = parser.parse_args()
    print(json.dumps(check_profile(args.profile, args.target), sort_keys=True))


if __name__ == "__main__":
    main()
