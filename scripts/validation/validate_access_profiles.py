#!/usr/bin/env python3
"""Access Profile과 canonical host-exposure boundary의 구조적 계약을 검증한다."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ai_model_serving.host_exposure import host_published_compose_services  # noqa: E402


_EXPECTED_ACCESS_PROFILES = {"local", "private", "edge"}
_SERVICE_REQUIRED_FIELDS = {
    "compose_service",
    "container_port",
    "host_env_port",
    "default_host_port",
    "host_env_bind",
    "default_bind",
    "categories",
}
_ACCESS_REQUIRED_FIELDS = {
    "description",
    "auth_mode",
    "exposure_audience",
    "host_bind_default",
    "host_bind_policy",
    "external_tls_owner",
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
    expected = host_published_compose_services(services)
    if not expected:
        violations.append(
            "services.yaml must classify at least one host-published public entrypoint"
        )
    return violations


def validate_access_profiles(
    access_data: dict[str, Any],
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

    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            violations.append(f"access profiles.{name} must be a mapping")
            continue
        missing = sorted(_ACCESS_REQUIRED_FIELDS - set(profile))
        if missing:
            violations.append(
                f"access profiles.{name} missing required fields: {', '.join(missing)}"
            )
            continue
        if "exposure_mode" in profile:
            violations.append(
                f"access profiles.{name} must not declare retired exposure_mode"
            )
        auth_mode = profile.get("auth_mode")
        if auth_mode not in auth_profiles:
            violations.append(
                f"access profiles.{name}.auth_mode references unknown auth profile {auth_mode!r}"
            )
        if profile.get("host_bind_default") not in {"127.0.0.1", "0.0.0.0"}:
            violations.append(
                f"access profiles.{name}.host_bind_default must be 127.0.0.1 or 0.0.0.0"
            )
        if profile.get("host_bind_policy") not in {"loopback", "operator"}:
            violations.append(
                f"access profiles.{name}.host_bind_policy must be loopback or operator"
            )

    expected_audience = {
        "local": "local_only",
        "private": "private_lan",
        "edge": "local_only",
    }
    for name, audience in expected_audience.items():
        profile = profiles.get(name)
        if isinstance(profile, dict) and profile.get("exposure_audience") != audience:
            violations.append(
                f"access {name} must declare exposure_audience={audience}"
            )

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
        for field in (
            "api_key_required",
            "admin_api_key_required",
            "internal_service_auth_required",
        ):
            if not isinstance(auth, dict) or auth.get(field) is not True:
                violations.append(
                    f"access private requires auth profile with {field}=true"
                )
    if isinstance(edge, dict):
        if (
            edge.get("host_bind_default") != "127.0.0.1"
            or edge.get("host_bind_policy") != "loopback"
        ):
            violations.append("access edge must use loopback host bind policy")
        if edge.get("external_tls_owner") != "edge_proxy":
            violations.append(
                "access edge must declare edge_proxy as external TLS owner"
            )

    host_published_ids = {
        service_id
        for service_id, service in services.items()
        if isinstance(service, dict)
        and str(service.get("compose_service", ""))
        in host_published_compose_services(services)
    }
    for service_id in host_published_ids:
        service = services.get(service_id)
        if not isinstance(service, dict) or not service.get("host_env_bind"):
            violations.append(
                f"host-published service {service_id} must define host_env_bind"
            )
    return violations


def _published_services_from_files(relative_paths: list[str]) -> set[str]:
    published: set[str] = set()
    for relative in relative_paths:
        path = ROOT / relative
        if not path.is_file():
            continue
        services = load(path).get("services")
        if not isinstance(services, dict):
            continue
        for name, service in services.items():
            if isinstance(service, dict) and service.get("ports"):
                published.add(str(name))
    return published


def validate_compose_projection(
    services: dict[str, Any],
    targets_data: dict[str, Any],
) -> list[str]:
    violations: list[str] = []

    dynamic_actual = _published_services_from_files(
        ["ops/compose/full-stack.private-network.yaml"]
    )
    dynamic_expected = set(host_published_compose_services(services))
    if dynamic_actual != dynamic_expected:
        violations.append(
            "full-stack host-published services differ from service-registry policy: "
            f"compose={sorted(dynamic_actual)}, expected={sorted(dynamic_expected)}"
        )

    targets = targets_data.get("targets")
    if not isinstance(targets, dict):
        return [*violations, "configs/deployment_targets.yaml targets field is missing"]

    for target_id, target in targets.items():
        if not isinstance(target, dict):
            continue
        compose_files = target.get("compose_files")
        if not isinstance(compose_files, list):
            continue
        actual = _published_services_from_files(
            [str(path) for path in compose_files if isinstance(path, str)]
        )
        include_visualization = target.get("runs_monitoring_stack") is True
        expected = set(
            host_published_compose_services(
                services,
                include_visualization=include_visualization,
            )
        )
        if actual != expected:
            violations.append(
                f"deployment target {target_id!r} host-published services differ from "
                "service-registry policy: "
                f"compose={sorted(actual)}, expected={sorted(expected)}"
            )
    return violations


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate Access Profile and canonical host-exposure invariants."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="actual Compose host-published services까지 service registry와 대조합니다.",
    )
    args = parser.parse_args()

    services = load_services(ROOT / "configs/services.yaml")
    access_data = load(ROOT / "configs/access_profiles.yaml")
    auth_data = load(ROOT / "configs/auth_profiles.yaml")
    targets_data = load(ROOT / "configs/deployment_targets.yaml")

    violations = validate_services(services)
    violations.extend(validate_access_profiles(access_data, auth_data, services))
    if args.strict and not violations:
        violations.extend(validate_compose_projection(services, targets_data))

    if violations:
        for violation in violations:
            print(f"FAIL: {violation}", file=sys.stderr)
        print(
            f"\nvalidate_access_profiles: {len(violations)} violation(s) found.",
            file=sys.stderr,
        )
        return 1

    print(
        "validate_access_profiles: OK — access and host-exposure contracts are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
