#!/usr/bin/env python3
"""`.env` 예시 파일들이 configs/env_contract.yaml에 선언된 키를 전부 갖고 있는지 검증한다.

체크 항목:
- env_contract.yaml에 선언된 env example이 각각 필요한 키 집합을 포함하는지
- 필요한 키 집합: 공통 예시 키, 인증 키, runtime override 키
- removed key가 active/commented assignment 또는 service env projection으로 재도입되지 않는지

사용법:
  python scripts/validation/validate_env_contract.py
  python scripts/validation/validate_env_contract.py --strict
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    import yaml
except ModuleNotFoundError:
    raise SystemExit("Missing dependency: PyYAML.")

from ai_model_serving.settings_parts.dotenv_parser import parse_env_file  # noqa: E402
from ai_model_serving.auth_control import auth_profile_env_values  # noqa: E402
from ai_model_serving.access_profile import access_profile_mismatches  # noqa: E402


_COMMENTED_ASSIGNMENT = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Expected YAML mapping at {path}")
    return data


def _commented_assignment_keys(path: Path) -> set[str]:
    """Return assignment-shaped keys offered inside comments of an env example."""
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _COMMENTED_ASSIGNMENT.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def expand_required_keys(
    contract: dict[str, Any],
    key_set_names: list[str],
    *,
    violations: list[str],
) -> list[str]:
    """env_contract.yaml의 key_set 참조 목록을 실제 키 이름들로 펼친다."""
    required: list[str] = []

    for name in key_set_names:
        if not isinstance(name, str) or not name:
            violations.append(
                "env_contract.yaml: required_key_sets entries must be non-empty strings"
            )
            continue
        if name in {"common_example_keys", "auth_mode_keys", "auth_evidence_keys"}:
            values = contract.get(name)
            if not isinstance(values, list):
                continue  # validate_contract_structure() reports the malformed block.
            required.extend(values)
        elif name == "runtime_override_example_keys":
            runtime_overrides = contract.get("runtime_override_example_keys")
            if not isinstance(runtime_overrides, dict):
                continue  # validate_contract_structure() reports the malformed block.
            for runtime_cfg in runtime_overrides.values():
                if not isinstance(runtime_cfg, dict):
                    continue
                prefix = runtime_cfg.get("env_prefix")
                suffixes = runtime_cfg.get("suffixes")
                if not isinstance(prefix, str) or not isinstance(suffixes, list):
                    continue
                for suffix in suffixes:
                    if not isinstance(suffix, str):
                        continue
                    required.append(f"{prefix}_{suffix}")
        else:
            # contract 최상위의 직접 목록
            val = contract.get(name)
            if isinstance(val, list):
                required.extend(val)
            else:
                violations.append(
                    f"env_contract.yaml: required key set {name!r} does not exist or is not a list"
                )

    return required


def _string_list(value: Any, *, label: str, violations: list[str]) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        violations.append(f"env_contract.yaml: {label} must be a non-empty string list")
        return []
    if len(set(value)) != len(value):
        violations.append(f"env_contract.yaml: {label} contains duplicate keys")
    return value


def validate_contract_structure(contract: dict[str, Any]) -> list[str]:
    """필수 contract 블록이 사라져 검사가 조용히 축소되지 않게 한다."""
    violations: list[str] = []
    for name in ("common_example_keys", "auth_mode_keys", "auth_evidence_keys"):
        _string_list(contract.get(name), label=name, violations=violations)

    runtime_overrides = contract.get("runtime_override_example_keys")
    if not isinstance(runtime_overrides, dict) or not runtime_overrides:
        violations.append(
            "env_contract.yaml: runtime_override_example_keys must be a non-empty mapping"
        )
    else:
        for name, raw in runtime_overrides.items():
            label = f"runtime_override_example_keys.{name}"
            if not isinstance(raw, dict):
                violations.append(f"env_contract.yaml: {label} must be a mapping")
                continue
            if not isinstance(raw.get("env_prefix"), str) or not raw["env_prefix"]:
                violations.append(f"env_contract.yaml: {label}.env_prefix must be non-empty")
            _string_list(raw.get("suffixes"), label=f"{label}.suffixes", violations=violations)

    env_examples = contract.get("env_examples")
    if not isinstance(env_examples, dict) or not env_examples:
        violations.append("env_contract.yaml: env_examples must be a non-empty mapping")
    else:
        for filename, raw in env_examples.items():
            label = f"env_examples.{filename}"
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not filename.endswith(".example")
            ):
                violations.append(
                    f"env_contract.yaml: {label} must use a top-level .example filename"
                )
            if not isinstance(raw, dict):
                violations.append(f"env_contract.yaml: {label} must be a mapping")
                continue
            _string_list(
                raw.get("required_key_sets"),
                label=f"{label}.required_key_sets",
                violations=violations,
            )

    return violations


def validate_service_env_projections(root: Path, contract: dict[str, Any]) -> list[str]:
    """Verify target-scoped process-env projections without reading secret values."""
    violations: list[str] = []
    projections = contract.get("service_env_projections")
    if not isinstance(projections, dict) or not projections:
        return [
            "env_contract.yaml: service_env_projections must be a non-empty mapping"
        ]

    removed = contract.get("removed_keys")
    removed_keys = set(removed) if isinstance(removed, dict) else set()
    targets_path = root / "configs" / "deployment_targets.yaml"
    targets_document = load_yaml(targets_path) if targets_path.exists() else {}
    targets = targets_document.get("targets") if isinstance(targets_document.get("targets"), dict) else {}
    projected_consumers: set[tuple[str, str]] = set()
    for name, raw in projections.items():
        label = f"service_env_projections.{name}"
        if not isinstance(raw, dict):
            violations.append(f"env_contract.yaml: {label} must be a mapping")
            continue
        projection_targets = _string_list(
            raw.get("deployment_targets"),
            label=f"{label}.deployment_targets",
            violations=violations,
        )
        service = raw.get("service")
        if not isinstance(service, str) or not service.strip():
            violations.append(f"env_contract.yaml: {label}.service must be a non-empty string")
            service = ""
        else:
            service = service.strip()
        if not projection_targets:
            continue
        known_projection_targets: list[tuple[str, dict[str, Any]]] = []
        for target in projection_targets:
            target_cfg = targets.get(target)
            if not isinstance(target_cfg, dict):
                violations.append(
                    f"env_contract.yaml: {label}.deployment_targets contains unknown target: {target!r}"
                )
                continue
            consumer = (target, service)
            if consumer in projected_consumers:
                violations.append(
                    "env_contract.yaml: duplicate service env projection for "
                    f"target {target!r} and service {service!r}"
                )
            projected_consumers.add(consumer)
            known_projection_targets.append((target, target_cfg))
        required = _string_list(raw.get("required_source_keys"), label=f"{label}.required_source_keys", violations=violations)
        runtime = _string_list(raw.get("runtime_keys"), label=f"{label}.runtime_keys", violations=violations)
        omitted_required = set(required) - set(runtime)
        if omitted_required:
            violations.append(
                f"env_contract.yaml: {label}.required_source_keys missing from runtime_keys: "
                + ", ".join(sorted(omitted_required))
            )
        projected_removed = removed_keys & set(runtime)
        if projected_removed:
            violations.append(
                f"env_contract.yaml: {label}.runtime_keys contains removed persistent key(s): "
                + ", ".join(sorted(projected_removed))
            )
        if "DEPLOYMENT_TARGET" not in runtime:
            violations.append(f"env_contract.yaml: {label}.runtime_keys must include DEPLOYMENT_TARGET")
        for target, target_cfg in known_projection_targets:
            if target_cfg.get("internal_service_token_required") is False and "INTERNAL_SERVICE_TOKEN" in runtime:
                violations.append(
                    f"env_contract.yaml: {label} injects INTERNAL_SERVICE_TOKEN although target {target!r} has no token consumer"
                )
    compose_targets = {
        str(target): target_cfg
        for target, target_cfg in targets.items()
        if isinstance(target_cfg, dict) and isinstance(target_cfg.get("compose_files"), list)
    }
    if not compose_targets:
        return violations

    services_document = load_yaml(root / "configs" / "services.yaml")
    services = services_document.get("services")
    compose_to_service_id = {
        str(raw.get("compose_service")): str(service_id)
        for service_id, raw in (services.items() if isinstance(services, dict) else [])
        if isinstance(raw, dict) and raw.get("compose_service")
    }

    expected_consumers: set[tuple[str, str]] = set()
    for target, target_cfg in compose_targets.items():
        compose_files = target_cfg.get("compose_files")
        if not isinstance(compose_files, list):
            continue
        for relative in compose_files:
            if not isinstance(relative, str) or not relative:
                continue
            compose_path = root / relative
            if not compose_path.exists():
                continue
            compose_document = load_yaml(compose_path)
            compose_services = compose_document.get("services")
            if not isinstance(compose_services, dict):
                continue
            for compose_service, service_cfg in compose_services.items():
                if not isinstance(service_cfg, dict):
                    continue
                env_file = service_cfg.get("env_file")
                env_text = ""
                if isinstance(env_file, str):
                    env_text = env_file
                elif isinstance(env_file, list):
                    env_text = "\n".join(
                        str(item) for item in env_file if isinstance(item, (str, dict))
                    )
                if "RUNTIME_ENV_FILE" not in env_text:
                    continue
                service_id = compose_to_service_id.get(str(compose_service))
                if service_id is None:
                    violations.append(
                        f"{relative}: service {compose_service!r} uses a runtime env file "
                        "but has no canonical services.yaml identity"
                    )
                    continue
                expected_consumers.add((str(target), service_id))

    missing_consumers = expected_consumers - projected_consumers
    for target, service in sorted(missing_consumers):
        violations.append(
            "env_contract.yaml: missing service env projection for "
            f"target {target!r} and service {service!r}"
        )



    return violations


def validate_auth_example_profiles(root: Path, contract: dict[str, Any]) -> list[str]:
    """Validate the auth profile values carried by env examples.

    This belongs here rather than in a second CLI: both checks read the same
    template files and the env contract already owns each template's role.
    """
    violations: list[str] = []
    examples = contract.get("auth_example_profiles")
    if not isinstance(examples, dict) or not examples:
        return [
            "env_contract.yaml: auth_example_profiles must be a non-empty mapping"
        ]
    for filename, profile in examples.items():
        if not isinstance(filename, str) or not isinstance(profile, str) or not profile:
            violations.append("env_contract.yaml: auth_example_profiles entries must map filename to profile name")
            continue
        path = root / filename
        if not path.exists():
            violations.append(f"{filename}: file not found for auth profile validation")
            continue
        try:
            values = parse_env_file(path).values
        except RuntimeError as exc:
            violations.append(f"{filename}: invalid env syntax: {exc}")
            continue
        expected = auth_profile_env_values(profile)
        mismatches = {
            key: (values.get(key), expected_value)
            for key, expected_value in expected.items()
            if values.get(key) != expected_value
        }
        if mismatches:
            violations.append(f"{filename}: auth profile {profile!r} mismatch: {mismatches}")
        app_env = values.get("APP_ENV", "").lower()
        if app_env not in {"local", "test", "development"} and values.get("API_KEY_REQUIRED") != "true":
            violations.append(
                f"{filename}: non-local APP_ENV={values.get('APP_ENV', '')!r} requires API_KEY_REQUIRED=true"
            )
    return violations


def validate_access_example_profiles(root: Path, contract: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    examples = contract.get("access_example_profiles")
    if not isinstance(examples, dict) or not examples:
        return [
            "env_contract.yaml: access_example_profiles must be a non-empty mapping"
        ]
    for filename, profile in examples.items():
        if not isinstance(filename, str) or not isinstance(profile, str) or not profile:
            violations.append(
                "env_contract.yaml: access_example_profiles entries must map filename to profile name"
            )
            continue
        path = root / filename
        if not path.exists():
            violations.append(f"{filename}: file not found for access profile validation")
            continue
        try:
            values = parse_env_file(path).values
            mismatches = access_profile_mismatches(profile, values, root)
        except (OSError, RuntimeError, ValueError) as exc:
            violations.append(f"{filename}: access profile validation failed: {exc}")
            continue
        if mismatches:
            violations.append(
                f"{filename}: access profile {profile!r} mismatch: {mismatches}"
            )
    return violations


def validate(root: Path = ROOT) -> list[str]:
    violations: list[str] = []

    contract_path = root / "configs" / "env_contract.yaml"
    if not contract_path.exists():
        violations.append(f"configs/env_contract.yaml not found at {contract_path}")
        return violations

    contract = load_yaml(contract_path)
    violations.extend(validate_contract_structure(contract))
    env_examples = contract.get("env_examples")
    if not isinstance(env_examples, dict):
        env_examples = {}
    removed_keys = contract.get("removed_keys")
    if removed_keys is None:
        removed_keys = {}
    elif not isinstance(removed_keys, dict):
        violations.append("env_contract.yaml: removed_keys must be a mapping")
        removed_keys = {}
    violations.extend(validate_service_env_projections(root, contract))
    violations.extend(validate_auth_example_profiles(root, contract))
    violations.extend(validate_access_example_profiles(root, contract))
    main_profiles = load_yaml(
        root / "configs" / "main_model_profiles.yaml"
    ).get("profiles", {})
    services = load_yaml(root / "configs" / "services.yaml").get("services", {})
    expected_service_ports = {
        str(service["host_env_port"]): str(service["default_host_port"])
        for service in services.values()
        if isinstance(service, dict) and service.get("host_env_port")
    }

    for filename, cfg in env_examples.items():
        file_path = root / filename
        if not file_path.exists():
            violations.append(f"{filename}: file not found")
            continue

        parse_result = parse_env_file(file_path)
        violations.extend(parse_result.errors)
        values = parse_result.values
        present_keys = set(values)
        commented_assignments = _commented_assignment_keys(file_path)
        if not isinstance(cfg, dict):
            continue  # validate_contract_structure()가 보고한다.
        key_set_names = cfg.get("required_key_sets")
        if not isinstance(key_set_names, list):
            continue  # validate_contract_structure()가 보고한다.
        required_keys = list(
            dict.fromkeys(
                expand_required_keys(
                    contract,
                    key_set_names,
                    violations=violations,
                )
            )
        )

        for key in required_keys:
            if key not in present_keys:
                violations.append(f"{filename}: missing required key {key!r}")

        # removed_keys는 sync-env가 기존 .env에서 지우는 키다. 그 키가 예시 파일에
        # 다시 들어오면 두 동작이 정면으로 싸운다 -- active assignment뿐 아니라
        # `# KEY=...` 형태의 복사 가능한 예시도 persistent env surface를 다시 만든다.
        for key in sorted(removed_keys.keys() & present_keys):
            violations.append(
                f"{filename}: {key!r} is registered in env_contract.yaml removed_keys "
                f"(`make up` deletes it while syncing .env), so it must not be declared in the template "
                f"-- {removed_keys[key]}"
            )
        for key in sorted(removed_keys.keys() & commented_assignments):
            violations.append(
                f"{filename}: {key!r} is registered in env_contract.yaml removed_keys, "
                "so it must not be offered as a commented assignment in the template "
                f"-- {removed_keys[key]}"
            )

        static_profile = values.get("MAIN_MODEL_STATIC_PROFILE", "").strip()
        if "MAIN_MODEL_STATIC_PROFILE" in values and static_profile not in main_profiles:
            violations.append(
                f"{filename}: MAIN_MODEL_STATIC_PROFILE references unknown profile "
                f"{static_profile!r}"
            )

        for port_key, expected_port in expected_service_ports.items():
            if port_key in values and values[port_key].strip() != expected_port:
                violations.append(
                    f"{filename}: {port_key}={values[port_key].strip()} does not match "
                    f"configs/services.yaml default_host_port={expected_port}"
                )


    return violations


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate .env examples against configs/env_contract.yaml.")
    parser.parse_args()

    violations = validate(ROOT)

    if violations:
        for v in violations:
            print(f"FAIL: {v}", file=sys.stderr)
        print(f"\nvalidate_env_contract: {len(violations)} violation(s) found.", file=sys.stderr)
        return 1

    print("validate_env_contract: OK — .env examples match env_contract.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
