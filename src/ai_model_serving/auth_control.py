from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .configuration import load_yaml_mapping
from .host_exposure import host_published_service_ids
from .project_paths import resolve_project_root
from .settings import AppSettings
from .settings_parts.env import LOCAL_ENVIRONMENTS, default_env_path, env as _env


# ---------------------------------------------------------------------------
# YAML에서 auth 프로필을 로드한다 — configs/auth_profiles.yaml이 source of truth다.
# AUTH_MODE_EXPECTATIONS는 모듈 시작 시 이 YAML에서 파생되며, 수동으로
# 관리하는 dict가 아니다. auth 의미론 변경은 반드시 YAML을 먼저 수정한다.
# ---------------------------------------------------------------------------

# Image builds install the package in /app/.venv while configs live at /app/configs
# (and may be replaced by the read-only Compose mount).  Do not derive the
# config root from the installed module path; APP_CONFIG_ROOT owns that boundary.
_PROJECT_ROOT = resolve_project_root(required_paths=("configs/auth_profiles.yaml",))
_AUTH_PROFILES_YAML = _PROJECT_ROOT / "configs" / "auth_profiles.yaml"

_BOOL_FIELDS = (
    "api_key_required",
    "admin_api_key_required",
    "admin_endpoints_internal_only",
    "internal_service_auth_required",
    "docs_enabled",
)

_SEMANTIC_FIELDS = (
    "auth_owner",
    "scope",
)

_OPTIONAL_POLICY_FIELDS = ("default_exposure_audience",)

def _load_auth_profiles(yaml_path: Path) -> dict[str, dict[str, Any]]:
    """`configs/auth_profiles.yaml`을 읽어 인증 프로필 매핑을 반환한다."""
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"configs/auth_profiles.yaml not found at {yaml_path}. "
            "This file is the source of truth for auth mode expectations."
        )
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"configs/auth_profiles.yaml is not a valid YAML mapping: {yaml_path}")
    return data.get("profiles", {})


def _build_expectations(profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, bool | str]]:
    """YAML 프로필을 ``AUTH_MODE_EXPECTATIONS`` 형식으로 변환한다."""
    result: dict[str, dict[str, bool | str]] = {}
    for mode, profile in profiles.items():
        entry: dict[str, bool | str] = {}
        for field in _BOOL_FIELDS:
            if field in profile:
                entry[field] = bool(profile[field])
        for field in (*_SEMANTIC_FIELDS, *_OPTIONAL_POLICY_FIELDS):
            if field in profile:
                val = profile[field]
                entry[field] = bool(val) if isinstance(val, bool) else str(val)
        result[mode] = entry
    return result


_YAML_PROFILES: dict[str, dict[str, Any]] = _load_auth_profiles(_AUTH_PROFILES_YAML)
AUTH_MODE_EXPECTATIONS: dict[str, dict[str, bool | str]] = _build_expectations(_YAML_PROFILES)

AUTH_PROFILE_ENV_KEYS = (
    "AUTH_MODE",
    "API_KEY_REQUIRED",
    "ADMIN_API_KEY_REQUIRED",
    "ADMIN_ENDPOINTS_INTERNAL_ONLY",
    "INTERNAL_SERVICE_AUTH_REQUIRED",
    "FASTAPI_DOCS_ENABLED",
)


def auth_profile_env_values(mode: str) -> dict[str, str]:
    """관리되는 인증 프로필에 대응하는 구체적인 환경 변수 값을 반환한다.

    Secrets are intentionally not included. This helper is used by setup_env,
    auth-plan/apply tooling, tests, and docs so profile behavior does not drift
    across operator UX surfaces.
    """
    expected = AUTH_MODE_EXPECTATIONS.get(mode)
    if expected is None or mode == "custom":
        raise ValueError(f"{mode!r} is not a managed auth profile")
    return {
        "AUTH_MODE": mode,
        "API_KEY_REQUIRED": str(bool(expected.get("api_key_required", False))).lower(),
        "ADMIN_API_KEY_REQUIRED": str(bool(expected.get("admin_api_key_required", False))).lower(),
        "ADMIN_ENDPOINTS_INTERNAL_ONLY": str(bool(expected.get("admin_endpoints_internal_only", False))).lower(),
        "INTERNAL_SERVICE_AUTH_REQUIRED": str(bool(expected.get("internal_service_auth_required", False))).lower(),
        "FASTAPI_DOCS_ENABLED": str(bool(expected.get("docs_enabled", True))).lower(),
    }


def auth_profile_network_values(mode: str) -> dict[str, str]:
    """인증 프로필이 직접 소유하는 network-audience 기본값을 반환한다."""
    expected = AUTH_MODE_EXPECTATIONS.get(mode)
    if expected is None or mode == "custom":
        raise ValueError(f"{mode!r} is not a managed auth profile")
    audience = expected.get("default_exposure_audience")
    return {"EXPOSURE_AUDIENCE": str(audience)} if audience else {}


def auth_profile_network_mismatch(
    mode: str,
    exposure_audience: str,
) -> str | None:
    """Return the canonical auth/network-audience mismatch message, if any."""
    if mode != "local_open":
        return None
    expected = auth_profile_network_values(mode)
    required_audience = expected.get("EXPOSURE_AUDIENCE", "")
    if exposure_audience == required_audience:
        return None
    return f"AUTH_MODE={mode} requires EXPOSURE_AUDIENCE={required_audience}"


def auth_profile_summary(mode: str) -> str:
    expected = AUTH_MODE_EXPECTATIONS.get(mode, AUTH_MODE_EXPECTATIONS.get("custom", {}))
    return str(expected.get("scope", "운영자가 직접 관리하는 custom flag 조합"))


CUSTOM_AUTH_RISK_ACCEPTED_ENV = "CUSTOM_AUTH_RISK_ACCEPTED"
CUSTOM_AUTH_RISK_TICKET_ENV = "CUSTOM_AUTH_RISK_TICKET"


@dataclass(frozen=True)
class AuthFinding:
    level: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message}


def local_only_host_bind_mismatches(
    project_root: Path,
    *,
    read_value: Callable[[str, str], str] | None = None,
) -> list[str]:
    """local_only 선언과 실제 host-published loopback bind의 일치를 검증한다."""
    value = read_value or (lambda key, default: _env(key, default))
    services = load_yaml_mapping(project_root / "configs" / "services.yaml").get("services")
    if not isinstance(services, dict):
        return ["configs/services.yaml must define services"]

    mismatches: list[str] = []
    for service_id in sorted(host_published_service_ids(services)):
        service = services.get(service_id)
        if not isinstance(service, dict):
            mismatches.append(f"host-published service {service_id!r} is missing from services.yaml")
            continue
        bind_key = str(service.get("host_env_bind", "")).strip()
        default_bind = str(service.get("default_bind", "0.0.0.0")).strip()
        if not bind_key:
            mismatches.append(f"services.{service_id}.host_env_bind is required")
            continue
        actual = value(bind_key, default_bind).strip() or default_bind
        if actual != "127.0.0.1":
            mismatches.append(
                f"EXPOSURE_AUDIENCE=local_only requires {bind_key}=127.0.0.1 "
                f"for host-published {service_id}, got {actual!r}"
            )
    return mismatches


def auth_status_document(settings: AppSettings, project_root: Path, env_path: Path | None = None) -> dict[str, Any]:
    env_path = env_path or default_env_path(project_root)
    services = load_yaml_mapping(project_root / "configs" / "services.yaml").get("services")
    if not isinstance(services, dict):
        services = {}
    published = sorted(
        host_published_service_ids(
            services,
            include_visualization=settings.deployment_target.runs_monitoring_stack,
        )
    )
    retired_mode = _env("EXPOSURE_MODE", "").strip() or None

    auth_owner = AUTH_MODE_EXPECTATIONS.get(settings.security.auth_mode, {}).get("auth_owner", "app")
    return {
        "env_file": {
            "path": str(env_path),
            "exists": env_path.exists(),
            "repository_default": env_path.resolve() == default_env_path(project_root).resolve(),
        },
        "auth_mode": settings.security.auth_mode,
        "access_profile": _env("ACCESS_PROFILE", "").strip() or "legacy/custom",
        "app_env": settings.app_env,
        "mode_scope": AUTH_MODE_EXPECTATIONS.get(settings.security.auth_mode, {}).get("scope", "unknown"),
        "auth_owner": auth_owner,
        "retired_exposure_mode": retired_mode,
        "public_api": {
            "/v1/*": "api_key_required" if settings.security.api_key_required else "unauthenticated",
            **{
                path: "enabled" if settings.documentation.enabled else "disabled"
                for path in (
                    settings.documentation.docs_url,
                    settings.documentation.openapi_url,
                    "/static/*",
                )
            },
        },
        "admin_endpoints": {
            "/ready": "admin_key_required" if settings.security.admin_api_key_required else "no_app_token_required",
            "/metrics": "admin_key_required" if settings.security.admin_api_key_required else "no_app_token_required",
            "internal_only_declared": settings.security.admin_endpoints_internal_only,
            "app_level_cidr_enforcement": False,
        },
        "internal_services": {
            "gateway_to_risk_signal_service": "internal_token_required" if settings.security.internal_service_auth_required else "unauthenticated",
        },
        "host_exposure": {
            "host_published_services": published,
        },
    }

def diagnose_auth(settings: AppSettings, project_root: Path) -> list[AuthFinding]:
    findings: list[AuthFinding] = []
    mode = settings.security.auth_mode
    expected = AUTH_MODE_EXPECTATIONS.get(mode)
    if expected is None:
        findings.append(AuthFinding("WARN", "AUTH_MODE_UNKNOWN", f"AUTH_MODE={mode!r}는 알려진 profile이 아니므로 custom으로 해석합니다."))
        expected = AUTH_MODE_EXPECTATIONS.get("custom", {})

    if mode not in ("custom",):
        for key, actual in {
            "api_key_required": settings.security.api_key_required,
            "admin_api_key_required": settings.security.admin_api_key_required,
            "admin_endpoints_internal_only": settings.security.admin_endpoints_internal_only,
            "internal_service_auth_required": settings.security.internal_service_auth_required,
            "docs_enabled": settings.documentation.enabled,
        }.items():
            if key in expected and expected[key] != actual:
                findings.append(AuthFinding("WARN", "AUTH_MODE_FLAG_MISMATCH", f"AUTH_MODE={mode} 기대값은 {key}={expected[key]}인데 실제값은 {actual}입니다."))

    # 비로컬 판정의 기준은 LOCAL_ENVIRONMENTS의 여집합 하나다. 예전에는 앞에
    # NON_LOCAL_ENVS(staging/production/prod) 확인이 하나 더 있었지만, 그 집합은
    # LOCAL_ENVIRONMENTS와 서로소라 결과를 바꾼 적이 없다. 사본이 셋이었고 그중
    # 하나만 stage를 포함해 서로 달랐는데, 아무 동작 차이도 만들지 않았다.
    non_local = settings.app_env.lower() not in LOCAL_ENVIRONMENTS

    is_local_open_local_only = (
        mode == "local_open"
        and _env("EXPOSURE_AUDIENCE", "") == "local_only"
    )
    local_only_bind_mismatches = (
        local_only_host_bind_mismatches(project_root)
        if is_local_open_local_only
        else []
    )
    for mismatch in local_only_bind_mismatches:
        findings.append(AuthFinding("FAIL", "LOCAL_ONLY_BIND_MISMATCH", mismatch))
    local_only_boundary_valid = is_local_open_local_only and not local_only_bind_mismatches

    if non_local and mode == "custom":
        accepted = _env(CUSTOM_AUTH_RISK_ACCEPTED_ENV, "").lower() in ("1", "true")
        ticket = _env(CUSTOM_AUTH_RISK_TICKET_ENV, "").strip()
        if not accepted or not ticket:
            findings.append(AuthFinding(
                "FAIL",
                "CUSTOM_AUTH_RISK_ACCEPTANCE_REQUIRED",
                f"AUTH_MODE=custom in {settings.app_env} requires "
                f"{CUSTOM_AUTH_RISK_ACCEPTED_ENV}=true and {CUSTOM_AUTH_RISK_TICKET_ENV}.",
            ))

    if non_local and not settings.security.api_key_required:
        if local_only_boundary_valid:
            findings.append(AuthFinding(
                "INFO",
                "AUTH_DELEGATED_TO_NETWORK",
                f"AUTH_MODE={mode}: API_KEY_REQUIRED=false — 인증 소유권이 "
                f"loopback host 경계에 위임됨 (APP_ENV={settings.app_env}).",
            ))
        else:
            findings.append(AuthFinding("FAIL", "PUBLIC_API_UNAUTHENTICATED_NON_LOCAL", f"APP_ENV={settings.app_env}인데 API_KEY_REQUIRED=false입니다."))

    if non_local and not settings.security.internal_service_auth_required:
        if local_only_boundary_valid:
            findings.append(AuthFinding(
                "INFO",
                "INTERNAL_AUTH_DELEGATED",
                f"AUTH_MODE={mode}: INTERNAL_SERVICE_AUTH_REQUIRED=false — "
                f"내부 서비스 인증은 private Compose network 경계에 위임됨 (APP_ENV={settings.app_env}).",
            ))
        else:
            findings.append(AuthFinding("FAIL", "INTERNAL_SERVICE_AUTH_DISABLED_NON_LOCAL", f"APP_ENV={settings.app_env}인데 INTERNAL_SERVICE_AUTH_REQUIRED=false입니다."))

    if non_local and not settings.security.admin_api_key_required and not settings.security.admin_endpoints_internal_only:
        findings.append(AuthFinding("WARN", "ADMIN_ENDPOINTS_OPEN_NON_LOCAL", f"APP_ENV={settings.app_env}에서 ADMIN_API_KEY_REQUIRED=false 및 ADMIN_ENDPOINTS_INTERNAL_ONLY=false입니다."))
    if settings.security.admin_endpoints_internal_only and not settings.security.admin_api_key_required:
        findings.append(AuthFinding("WARN", "ADMIN_INTERNAL_ONLY_NOT_APP_ENFORCED", "ADMIN_ENDPOINTS_INTERNAL_ONLY=true는 배포/networking 선언이며 app-level CIDR enforcement는 아직 구현되지 않았습니다."))

    # Access/network 진단 — host topology는 고정 invariant이며 audience/bind만 policy다.
    exposure_audience = _env("EXPOSURE_AUDIENCE", "").strip()
    retired_mode = _env("EXPOSURE_MODE", "").strip()
    if retired_mode:
        level = "FAIL" if retired_mode != "private_network" else "WARN"
        findings.append(
            AuthFinding(
                level,
                "RETIRED_EXPOSURE_MODE_PRESENT",
                f"EXPOSURE_MODE={retired_mode!r} is retired; "
                "choose ACCESS=local|private|edge and remove the legacy key.",
            )
        )

    access_profile = _env("ACCESS_PROFILE", "").strip()
    if access_profile:
        from .access_profile import access_profile_env_values, access_profile_mismatches

        try:
            expected_access = access_profile_env_values(access_profile, project_root)
            current_access = {key: _env(key, "") for key in expected_access}
            access_mismatches = access_profile_mismatches(
                access_profile, current_access, project_root
            )
        except (OSError, ValueError) as exc:
            findings.append(AuthFinding("FAIL", "ACCESS_PROFILE_INVALID", str(exc)))
        else:
            for mismatch in access_mismatches:
                findings.append(
                    AuthFinding(
                        "FAIL",
                        "ACCESS_PROFILE_DRIFT",
                        f"ACCESS_PROFILE={access_profile}: {mismatch}",
                    )
                )
    else:
        network_mismatch = auth_profile_network_mismatch(mode, exposure_audience)
        if network_mismatch is not None:
            findings.append(
                AuthFinding(
                    "FAIL",
                    "LOCAL_OPEN_NETWORK_POLICY_MISMATCH",
                    network_mismatch + " so unauthenticated access remains loopback-only.",
                )
            )


    if not findings:
        findings.append(AuthFinding("OK", "AUTH_POLICY_OK", "인증 제어 플레인에서 발견된 문제가 없습니다."))
    return findings


def render_auth_status(settings: AppSettings, project_root: Path, env_path: Path | None = None) -> str:
    doc = auth_status_document(settings, project_root, env_path)
    lines = [
        f"접근 profile: {doc['access_profile']}",
        f"인증 profile: {doc['auth_mode']}",
        f"APP_ENV: {doc['app_env']}",
        f"인증 소유권: {doc['auth_owner']}",
        f"env 파일: {doc['env_file']['path'] if doc['env_file']['exists'] else str(doc['env_file']['path']) + ' (없음)'}",
        f"적용 범위: {doc['mode_scope']}",
        "",
        "Public API",
    ]
    for name, state in doc["public_api"].items():
        lines.append(f"  {name:<22} {state}")
    lines.extend(["", "Admin endpoint"])
    for name in ["/ready", "/metrics"]:
        lines.append(f"  {name:<22} {doc['admin_endpoints'][name]}")
    lines.append(f"  internal_only 선언    {doc['admin_endpoints']['internal_only_declared']}")
    lines.append(f"  app CIDR enforcement  {doc['admin_endpoints']['app_level_cidr_enforcement']}")
    lines.extend(["", "Internal service"])
    lines.append(f"  Gateway -> Risk Signal Service {doc['internal_services']['gateway_to_risk_signal_service']}")
    lines.extend(["", "Host exposure"])
    exposure = doc["host_exposure"]
    lines.append(
        f"  Host-published: {', '.join(exposure['host_published_services']) if exposure['host_published_services'] else 'none'}"
    )
    if doc["retired_exposure_mode"]:
        lines.append(
            f"  Retired EXPOSURE_MODE marker: {doc['retired_exposure_mode']} (migration required)"
        )
    env_info = doc["env_file"]
    if not env_info["exists"]:
        lines.extend([
            "",
            "안내",
            "  지정된 env 파일이 없어 기본 설정값으로 상태를 표시했습니다.",
            "  실제 운영 전에는 app-only 개발은 `make init-env-local`, full-stack 운영은 `make up TARGET=<deployment-target>`으로 env를 준비한 뒤 다시 확인하세요.",
        ])
    elif not env_info["repository_default"]:
        lines.extend([
            "",
            "안내",
            "  --env로 지정한 파일을 기준으로 인증 상태를 표시했습니다.",
            "  repository root .env에는 자동 반영하지 않습니다.",
        ])
    return "\n".join(lines) + "\n"


def render_auth_findings(findings: list[AuthFinding]) -> str:
    return "\n".join(f"{finding.level}: {finding.code}: {finding.message}" for finding in findings) + "\n"
