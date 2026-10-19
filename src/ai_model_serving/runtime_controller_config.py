"""Runtime Controller 설정 해석: Docker 실행·HTTP 서버와 독립적인 모듈."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .configuration import load_yaml_mapping
from .platform_state import DEFAULT_PLATFORM_STATE_DIR, configured_platform_state_root
from .settings_parts.env import as_bool, is_default_secret


@dataclass(frozen=True)
class RuntimeControllerConfig:
    docker_socket: str
    compose_project: str
    config_root: Path
    state_path: Path
    boot_profile: str | None
    profile_locked: bool
    idempotency_ttl_seconds: str | None
    internal_service_token: str
    internal_service_auth_required: bool
    gateway_internal_url: str
    log_target_manifest_path: Path
    log_target_refresh_seconds: float


def _default_gateway_internal_url(config_root: Path) -> str:
    services = load_yaml_mapping(config_root / "configs/services.yaml")["services"]
    gateway = services["gateway"]
    return f"http://{gateway['compose_service']}:{gateway['container_port']}"


def load_runtime_controller_config(
    environment: Mapping[str, str], *, source_path: Path | None = None
) -> RuntimeControllerConfig:
    """Docker import나 백그라운드 작업 시작 없이 Runtime Controller 설정을 해석한다."""
    configured_root = Path(environment.get("APP_CONFIG_ROOT", "/app"))
    using_local_config = not (configured_root / "configs/main_model_profiles.yaml").exists()
    # source_path는 기존 apps/runtime_controller.py 경로를 전달하는 호출자와의 호환성이다.
    # 기본값은 이 설정 모듈 자신의 위치에서 프로젝트 루트를 계산한다.
    config_root = (
        (source_path.resolve().parents[3] if source_path is not None else Path(__file__).resolve().parents[2])
        if using_local_config else configured_root
    )
    configured_state_root = configured_platform_state_root(environment)
    if using_local_config and configured_state_root is None:
        default_state_path = config_root / ".runtime/main-model/main-model-state.json"
        default_log_target_manifest_path = config_root / ".runtime/log-targets/docker-containers.json"
    else:
        platform_state_root = configured_state_root or DEFAULT_PLATFORM_STATE_DIR
        default_state_path = platform_state_root / "main-model-state.json"
        default_log_target_manifest_path = platform_state_root / "log-targets/docker-containers.json"
    # 인증 활성 여부는 토큰 문자열이 비었는지가 아니라 운영자가 선언한
    # INTERNAL_SERVICE_AUTH_REQUIRED로 정한다. 빈 문자열을 곧 "인증 끔"으로 읽으면,
    # private_network/strict처럼 내부 인증을 요구한 profile에서 토큰이 유실됐을 때
    # Docker socket을 쥔 이 프로세스가 거부 대신 조용한 개방을 택하게 된다.
    # 기본값이 False인 것은 의도다 -- 변수를 주입하지 않는 로컬 실행은 지금 동작을
    # 그대로 유지해야 한다. Compose는 setup_env가 쓴 값을 항상 주입한다.
    internal_service_token = environment.get("INTERNAL_SERVICE_TOKEN", "")
    internal_service_auth_required = as_bool(
        environment.get("INTERNAL_SERVICE_AUTH_REQUIRED"), False
    )
    if internal_service_auth_required and is_default_secret(internal_service_token):
        raise RuntimeError(
            "INTERNAL_SERVICE_TOKEN must be set to a non-default value when "
            "INTERNAL_SERVICE_AUTH_REQUIRED=true. Initialize with `make up TARGET=<deployment-target>` or set a non-default token in the existing .env."
        )
    log_refresh_seconds = float(environment.get("LOG_TARGET_REFRESH_SECONDS", "15"))
    if not math.isfinite(log_refresh_seconds) or log_refresh_seconds <= 0:
        raise RuntimeError("LOG_TARGET_REFRESH_SECONDS must be a finite positive number")
    return RuntimeControllerConfig(
        docker_socket=environment.get("DOCKER_SOCKET", "/var/run/docker.sock"),
        compose_project=environment.get("COMPOSE_PROJECT", ""),
        config_root=config_root,
        state_path=Path(environment.get("MAIN_MODEL_STATE_PATH", str(default_state_path))),
        boot_profile=environment.get("MAIN_MODEL_BOOT_PROFILE") or None,
        profile_locked=as_bool(environment.get("MAIN_MODEL_PROFILE_LOCKED"), False),
        idempotency_ttl_seconds=environment.get("MAIN_MODEL_SWITCH_IDEMPOTENCY_TTL_SECONDS") or None,
        internal_service_token=internal_service_token,
        internal_service_auth_required=internal_service_auth_required,
        gateway_internal_url=environment.get("GATEWAY_INTERNAL_URL") or _default_gateway_internal_url(config_root),
        log_target_manifest_path=Path(
            environment.get(
                "LOG_TARGET_MANIFEST_PATH",
                str(default_log_target_manifest_path),
            )
        ),
        log_target_refresh_seconds=log_refresh_seconds,
    )


