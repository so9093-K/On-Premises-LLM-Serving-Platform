from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .access_profile import AccessProfile, load_access_profile
from .configuration import load_yaml_mapping
from .port_namespace import load_port_namespace
from .configuration_schema import CONFIGURATION_SCHEMA_VERSION
from .host_exposure import host_published_service_ids
from .project_paths import resolve_project_root
from .settings_parts.env import env as _env
from .settings_parts.types import AppSettings


BOOTSTRAP_VERSION = 4
_LEGACY_PROFILE = "legacy/custom"
_LEGACY_PROFILE_DESCRIPTION = (
    "Access Profile이 선택되지 않은 advanced/custom 구성입니다. 저수준 인증·노출 설정을 진단용으로 사용합니다."
)


@dataclass(frozen=True)
class ControlPlaneBootstrapProjection:
    """기동 시 해석하는 브라우저 공개용 Control Plane 탐색 입력.

    저장소 YAML과 프로세스 환경변수는 앱 구성 입력이며 요청마다 읽는 의존성이 아니다.
    Gateway는 앱 구성 시 한 번 해석한다. 공개 Bootstrap 요청은 현재
    Configuration Plane 상태와 로컬 Grafana 직접 연결에 필요한 요청 Hostname만 더한다.
    """

    platform_version: str
    deployment_target: str
    deployment_display_name: str
    deployment_platform: str
    runtime_backend: str
    implementation_status: str
    qualification_status: str
    control_mode: str
    lifecycle_owner: str
    features: tuple[str, ...]
    access_profile: str
    access_description: str
    admin_auth_required: bool
    monitoring_available: bool
    grafana_available: bool
    grafana_direct_port: int | None
    docs_url: str | None
    openapi_url: str | None


def _current_access_profile(root: Path) -> AccessProfile | None:
    """명시적으로 선택한 Managed Access Profile만 반환한다."""
    name = _env("ACCESS_PROFILE", "").strip()
    if not name:
        return None
    try:
        return load_access_profile(name, root)
    except ValueError:
        # 저수준 인증·네트워크 Flag를 역추론해 임의의 Access Profile로 표시하지 않는다.
        # Profile 선택이 없거나 알 수 없는 경우 기존·맞춤 설정 상태로 남긴다.
        return None


def _published_services(settings: AppSettings, root: Path) -> set[str]:
    services = load_yaml_mapping(root / "configs" / "services.yaml").get("services")
    if not isinstance(services, dict):
        return set()
    return set(
        host_published_service_ids(
            services,
            include_visualization=settings.deployment_target.runs_monitoring_stack,
        )
    )


def _service_host_port(root: Path, service_id: str) -> int | None:
    services = load_yaml_mapping(root / "configs" / "services.yaml").get("services")
    service = services.get(service_id) if isinstance(services, dict) else None
    if not isinstance(service, dict):
        return None
    env_key = service.get("host_env_port")
    default = service.get("default_host_port")
    if not isinstance(env_key, str) or isinstance(default, bool) or not isinstance(default, int):
        return None
    # 서비스별 override가 없으면 배포 포트 대역의 같은 역할 포트를 쓴다.
    default = load_port_namespace(root).translate(default)
    raw = _env(env_key, str(default)).strip()
    if not raw.isascii() or not raw.isdecimal():
        return None
    port = int(raw)
    return port if 1 <= port <= 65535 else None


def _grafana_projection(
    *,
    settings: AppSettings,
    root: Path,
    profile: AccessProfile | None,
) -> tuple[bool, int | None]:
    if not settings.deployment_target.runs_monitoring_stack:
        return False, None
    if "grafana" not in _published_services(settings, root):
        return False, None

    # Monitoring 서비스가 있어도 브라우저용 직접 URL이 없을 수 있다.
    # Private·Edge Profile에서는 TLS·Proxy 권한이 Gateway 외부에 있을 수 있으므로
    # 외부 TLS 소유자가 없는 Managed Profile에서만 Host Port를 직접 투영한다.
    if profile is None or profile.external_tls_owner != "none":
        return True, None
    return True, _service_host_port(root, "grafana")


def build_control_plane_bootstrap_projection(
    settings: AppSettings,
    *,
    root: Path | None = None,
) -> ControlPlaneBootstrapProjection:
    """Gateway 구성 시 저장소와 환경변수의 배포 상태를 한 번 해석한다."""
    project_root = resolve_project_root(root)
    profile = _current_access_profile(project_root)
    grafana_available, grafana_direct_port = _grafana_projection(
        settings=settings,
        root=project_root,
        profile=profile,
    )
    docs_enabled = settings.documentation.enabled
    target = settings.deployment_target
    return ControlPlaneBootstrapProjection(
        platform_version=settings.project_version,
        deployment_target=target.target_id,
        deployment_display_name=target.display_name,
        deployment_platform=target.platform,
        runtime_backend=target.runtime_backend,
        implementation_status=target.implementation_status,
        qualification_status=target.qualification_status,
        control_mode=target.control_mode,
        lifecycle_owner=target.lifecycle_owner,
        features=tuple(sorted(target.features)),
        access_profile=profile.name if profile is not None else _LEGACY_PROFILE,
        access_description=(
            profile.description if profile is not None else _LEGACY_PROFILE_DESCRIPTION
        ),
        admin_auth_required=settings.security.admin_api_key_required,
        monitoring_available=target.runs_monitoring_stack,
        grafana_available=grafana_available,
        grafana_direct_port=grafana_direct_port,
        docs_url=settings.documentation.docs_url if docs_enabled else None,
        openapi_url=settings.documentation.openapi_url if docs_enabled else None,
    )


def control_plane_bootstrap_document(
    projection: ControlPlaneBootstrapProjection,
    *,
    configuration_revision: int,
    configuration_write_available: bool,
    request_hostname: str | None,
) -> dict[str, Any]:
    """저장소 I/O 없이 브라우저 공개용 탐색 문서를 생성한다."""
    grafana_href = None
    if projection.grafana_direct_port is not None and request_hostname:
        host = f"[{request_hostname}]" if ":" in request_hostname else request_hostname
        grafana_href = f"http://{host}:{projection.grafana_direct_port}/"

    return {
        "bootstrap_version": BOOTSTRAP_VERSION,
        "platform": {
            "version": projection.platform_version,
        },
        "deployment": {
            "target": projection.deployment_target,
            "display_name": projection.deployment_display_name,
            "platform": projection.deployment_platform,
            "runtime_backend": projection.runtime_backend,
            "implementation_status": projection.implementation_status,
            "qualification_status": projection.qualification_status,
            "control_mode": projection.control_mode,
            "lifecycle_owner": projection.lifecycle_owner,
            "features": list(projection.features),
        },
        "access": {
            "profile": projection.access_profile,
            "description": projection.access_description,
            "admin_auth_required": projection.admin_auth_required,
        },
        "configuration": {
            "schema_version": CONFIGURATION_SCHEMA_VERSION,
            "revision": configuration_revision,
            "write_available": configuration_write_available,
        },
        "monitoring": {
            "available": projection.monitoring_available,
            "grafana_available": projection.grafana_available,
        },
        "links": {
            "docs": projection.docs_url,
            "openapi": projection.openapi_url,
            "grafana": grafana_href,
        },
    }
