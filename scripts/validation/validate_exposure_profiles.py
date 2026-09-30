#!/usr/bin/env python3
"""Access Profile과 단일 private host-exposure topology의 구조적 계약을 검증한다."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
_EXPECTED_ACCESS_PROFILES = {"local", "private", "edge"}
_EXPECTED_EXPOSURE_PROFILE = "private_network"
_EXPECTED_HOST_PUBLISHED = {"gateway", "grafana"}
_SERVICE_REQUIRED_FIELDS = {
    "compose_service",
    "container_port",
    "host_env_port",
    "default_host_port",
    "host_env_bind",
    "default_bind",
    "categories",
}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Expected YAML mapping at {path}")
    return data


def load_services(path: Path) -> dict[str, Any]:
    data = load(path)
    services = data.get("services")
    if not isinstance(services, dict):
        raise SystemExit(f"configs/services.yaml must contain services mapping: {path}")
    return services


def validate_exposure_profile(exposure_data: dict[str, Any], services: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    profiles = exposure_data.get("profiles")
    if not isinstance(profiles, dict):
        return ["configs/exposure_profiles.yaml profiles field is missing"]
    if set(profiles) != {_EXPECTED_EXPOSURE_PROFILE}:
        return [
            "exposure profiles must contain only private_network; "
            f"found={sorted(str(name) for name in profiles)}"
        ]
    profile = profiles.get(_EXPECTED_EXPOSURE_PROFILE)
    if not isinstance(profile, dict):
        return ["profiles.private_network must be a mapping"]
    if profile.get("class") != "default_private":
        violations.append("profiles.private_network.class must be default_private")
    published = profile.get("host_published")
    if not isinstance(published, list) or not all(isinstance(item, str) and item for item in published):
        violations.append("profiles.private_network.host_published must be a string list")
        published = []
    if len(set(published)) != len(published):
        violations.append("profiles.private_network.host_published must not contain duplicates")
    if set(published) != _EXPECTED_HOST_PUBLISHED:
        violations.append(
            "private_network must host-publish only gateway and grafana; "
            f"found={sorted(published)}"
        )
    unknown = sorted(set(published) - set(services))
    if unknown:
        violations.append(
            "profiles.private_network.host_published references unknown services: "
            + ", ".join(unknown)
        )
    diagnostics = profile.get("diagnostics")
    if not isinstance(diagnostics, dict):
        violations.append("profiles.private_network.diagnostics must be a mapping")
    elif any(bool(value) for value in diagnostics.values()):
        violations.append("private_network diagnostics must all be false")
    return violations


def validate_services(services: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for name, service in services.items():
        if not isinstance(service, dict):
            violations.append(f"services.{name} must be a mapping")
            continue
        missing = sorted(_SERVICE_REQUIRED_FIELDS - set(service))
        if missing:
            violations.append(
                f"services.{name} missing required fields: {', '.join(missing)}"
            )
        categories = service.get("categories")
        if not isinstance(categories, list) or not categories:
            violations.append(f"services.{name}.categories must be a non-empty list")
        for field in ("container_port", "default_host_port"):
            value = service.get(field)
            if isinstance(value, bool):
                violations.append(f"services.{name}.{field} must be numeric")
                continue
            try:
                int(value)
            except (TypeError, ValueError):
                violations.append(f"services.{name}.{field} must be numeric")
    return violations


def validate_access_profiles(
    access_data: dict[str, Any],
    exposure_data: dict[str, Any],
    auth_data: dict[str, Any],
    services: dict[str, Any],
) -> list[str]:
    violations: list[str] = []
    profiles = access_data.get("profiles")
    if not isinstance(profiles, dict):
        return ["configs/access_profiles.yaml profiles field is missing"]
    if set(profiles) != _EXPECTED_ACCESS_PROFILES:
        violations.append(
            "access profiles must be exactly local, private, edge; "
            f"found={sorted(str(name) for name in profiles)}"
        )
    if access_data.get("default_profile") != "local":
        violations.append("access default_profile must be local")

    auth_profiles = auth_data.get("profiles")
    if not isinstance(auth_profiles, dict):
        auth_profiles = {}
    exposure_profiles = exposure_data.get("profiles")
    if not isinstance(exposure_profiles, dict):
        exposure_profiles = {}

    required = {
        "description",
        "auth_mode",
        "exposure_mode",
        "exposure_audience",
        "host_bind_default",
        "host_bind_policy",
        "external_tls_owner",
    }
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            violations.append(f"access profiles.{name} must be a mapping")
            continue
        missing = sorted(required - set(profile))
        if missing:
            violations.append(
                f"access profiles.{name} missing required fields: {', '.join(missing)}"
            )
            continue
        auth_mode = profile.get("auth_mode")
        if auth_mode not in auth_profiles:
            violations.append(
                f"access profiles.{name}.auth_mode references unknown auth profile {auth_mode!r}"
            )
        if profile.get("exposure_mode") != _EXPECTED_EXPOSURE_PROFILE:
            violations.append(f"access profiles.{name}.exposure_mode must be private_network")
        elif profile.get("exposure_mode") not in exposure_profiles:
            violations.append(
                f"access profiles.{name}.exposure_mode references missing private_network profile"
            )
        if profile.get("host_bind_default") not in {"127.0.0.1", "0.0.0.0"}:
            violations.append(
                f"access profiles.{name}.host_bind_default must be 127.0.0.1 or 0.0.0.0"
            )
        if profile.get("host_bind_policy") not in {"loopback", "operator"}:
            violations.append(
                f"access profiles.{name}.host_bind_policy must be loopback or operator"
            )

    expected_audience = {"local": "local_only", "private": "private_lan", "edge": "local_only"}
    for name, audience in expected_audience.items():
        profile = profiles.get(name)
        if isinstance(profile, dict) and profile.get("exposure_audience") != audience:
            violations.append(f"access {name} must declare exposure_audience={audience}")

    local = profiles.get("local", {})
    private = profiles.get("private", {})
    edge = profiles.get("edge", {})
    if isinstance(local, dict) and (
        local.get("host_bind_default") != "127.0.0.1"
        or local.get("host_bind_policy") != "loopback"
    ):
        violations.append("access local must use loopback host bind policy")
    if isinstance(private, dict):
        if private.get("host_bind_policy") != "operator":
            violations.append("access private must preserve operator-selected host binds")
        auth = auth_profiles.get(private.get("auth_mode"), {})
        for field in ("api_key_required", "admin_api_key_required", "internal_service_auth_required"):
            if not isinstance(auth, dict) or auth.get(field) is not True:
                violations.append(f"access private requires auth profile with {field}=true")
    if isinstance(edge, dict):
        if (
            edge.get("host_bind_default") != "127.0.0.1"
            or edge.get("host_bind_policy") != "loopback"
        ):
            violations.append("access edge must use loopback host bind policy")
        if edge.get("external_tls_owner") != "edge_proxy":
            violations.append("access edge must declare edge_proxy as external TLS owner")

    if not any(
        isinstance(service, dict) and service.get("host_env_bind")
        for service in services.values()
    ):
        violations.append("services.yaml must define host bind keys")
    return violations


def validate_compose_projection(
    exposure_data: dict[str, Any],
    services: dict[str, Any],
) -> list[str]:
    compose = load(ROOT / "ops/compose/full-stack.private-network.yaml")
    compose_services = compose.get("services")
    if not isinstance(compose_services, dict):
        return ["full-stack private Compose must define services"]
    actual = {
        str(name)
        for name, service in compose_services.items()
        if isinstance(service, dict) and service.get("ports")
    }
    profile = exposure_data.get("profiles", {}).get(_EXPECTED_EXPOSURE_PROFILE, {})
    published = profile.get("host_published", []) if isinstance(profile, dict) else []
    expected = {
        str(services[service_id]["compose_service"])
        for service_id in published
        if service_id in services and isinstance(services[service_id], dict)
    }
    if actual != expected:
        return [
            "full-stack host-published Compose services differ from private_network profile: "
            f"compose={sorted(actual)}, profile={sorted(expected)}"
        ]
    return []


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate Access Profile and private host-exposure invariants."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="base Compose host-published services까지 private_network profile과 대조합니다.",
    )
    args = parser.parse_args()

    exposure_data = load(ROOT / "configs/exposure_profiles.yaml")
    services = load_services(ROOT / "configs/services.yaml")
    access_data = load(ROOT / "configs/access_profiles.yaml")
    auth_data = load(ROOT / "configs/auth_profiles.yaml")

    violations = validate_services(services)
    violations.extend(validate_exposure_profile(exposure_data, services))
    violations.extend(validate_access_profiles(access_data, exposure_data, auth_data, services))
    if args.strict and not violations:
        violations.extend(validate_compose_projection(exposure_data, services))

    if violations:
        for violation in violations:
            print(f"FAIL: {violation}", file=sys.stderr)
        print(
            f"\nvalidate_exposure_profiles: {len(violations)} violation(s) found.",
            file=sys.stderr,
        )
        return 1

    print("validate_exposure_profiles: OK — access/private exposure contracts are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
