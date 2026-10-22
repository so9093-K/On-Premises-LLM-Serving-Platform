"""배포가 선택한 포트 대역에서 프로젝트 소유 포트를 계산한다.

`configs/services.yaml`의 `port_namespace`가 기본 대역과 역할별 offset을 소유한다.
배포는 `.env`의 `PLATFORM_PORT_BASE`로 대역만 선택한다. 저장소의 설정 파일은 기본
대역 값을 그대로 유지하고, 실행 경로가 이 모듈로 같은 역할의 현재 포트를 계산한다.
대역 변경은 소스·문서·생성물을 고치는 작업이 아니라 배포 설정 하나의 변경이다.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .configuration import load_yaml_mapping
from .project_paths import resolve_project_root

PORT_BASE_ENV = "PLATFORM_PORT_BASE"

# Compose 보간 변수. 내부 포트를 `.env`에 복제하지 않고 실행할 때 이 값으로 투영한다.
COMPOSE_PORT_VARIABLES = {
    "gateway": "PLATFORM_PORT_GATEWAY",
    "main_llm_vllm": "PLATFORM_PORT_MAIN_LLM",
    "embedding_vllm": "PLATFORM_PORT_EMBEDDING",
    "embedding_ko_vllm": "PLATFORM_PORT_EMBEDDING_KO",
    "prompt_injection_detector_runtime": "PLATFORM_PORT_PROMPT_DETECTOR",
    "risk_signal_service": "PLATFORM_PORT_RISK",
    "grafana": "PLATFORM_PORT_GRAFANA",
    "mlx_metrics_exporter": "PLATFORM_PORT_MLX_EXPORTER",
}

# 운영자가 서비스별로 따로 지정할 수 있는 Host 포트다. 비어 있으면 대역 포트를 사용한다.
HOST_PORT_OVERRIDES = {
    "gateway": "GATEWAY_PORT",
    "grafana": "GRAFANA_PORT",
    "risk_signal_service": "RISK_SIGNAL_SERVICE_PORT",
}


def validate_port_base(value: int, offsets: Mapping[str, int]) -> int:
    if value < 1100 or value % 100 != 0 or value + max(offsets.values()) > 65535:
        raise ValueError(
            "포트 대역은 1100 이상, 100 단위의 시작 번호여야 합니다 "
            f"(마지막 포트 {max(offsets.values())}번 offset이 65535를 넘지 않아야 함)"
        )
    return value


@dataclass(frozen=True)
class PortNamespace:
    base: int
    default_base: int
    offsets: Mapping[str, int]
    compose_services: Mapping[str, str]

    def port(self, role: str) -> int:
        return self.base + self.offsets[role]

    def translate(self, port: int) -> int:
        """기본 대역의 역할 포트를 현재 대역의 같은 역할 포트로 옮긴다.

        DCGM 9400처럼 외부 엔진이 소유한 포트는 호출부가 넘기지 않는다.
        기본 대역에 속하지 않는 포트는 그대로 둔다.
        """
        offset = port - self.default_base
        if offset in self.offsets.values():
            return self.base + offset
        return port

    def translate_url(self, url: str) -> str:
        """URL의 authority 포트만 옮긴다. 경로·쿼리·호스트는 유지한다."""
        parts = urlsplit(url)
        if parts.port is None:
            return url
        translated = self.translate(parts.port)
        if translated == parts.port:
            return url
        host = parts.netloc.rsplit(":", 1)[0]
        return urlunsplit(parts._replace(netloc=f"{host}:{translated}"))

    def managed_role(self, hostname: str | None) -> str | None:
        """Compose 내부 서비스 이름이 가리키는 포트 역할을 반환한다."""
        for role, service in self.compose_services.items():
            if hostname == service:
                return role
        return None

    def host_port(self, role: str, environment: Mapping[str, str]) -> int:
        """Host에 공개되는 포트. 서비스별 override가 있으면 그것을 따른다."""
        key = HOST_PORT_OVERRIDES.get(role)
        raw = (environment.get(key, "") if key else "").strip()
        if raw:
            if not raw.isdecimal() or not 1 <= int(raw) <= 65535:
                raise ValueError(f"{key}={raw!r}는 1~65535 정수 포트여야 합니다")
            return int(raw)
        return self.port(role)

    def compose_variables(self, environment: Mapping[str, str]) -> dict[str, str]:
        values = {name: str(self.port(role)) for role, name in COMPOSE_PORT_VARIABLES.items()}
        # Host 공개 포트도 Compose가 같은 계산 결과를 쓰도록 함께 투영한다.
        values["GATEWAY_PORT"] = str(self.host_port("gateway", environment))
        values["GRAFANA_PORT"] = str(self.host_port("grafana", environment))
        return values


def parse_port_base(raw: str, offsets: Mapping[str, int], default: int) -> int:
    value = raw.strip()
    if not value:
        return default
    if not value.isdecimal():
        raise ValueError(f"{PORT_BASE_ENV}={raw!r}는 정수여야 합니다")
    return validate_port_base(int(value), offsets)


def port_namespace_from_services(
    services_document: Mapping[str, Any],
    environment: Mapping[str, str] | None = None,
) -> PortNamespace:
    policy = services_document.get("port_namespace")
    if not isinstance(policy, dict):
        raise ValueError("configs/services.yaml에 port_namespace가 없습니다")
    default_base = policy.get("base")
    offsets = policy.get("offsets")
    if not isinstance(default_base, int) or not isinstance(offsets, dict):
        raise ValueError("port_namespace.base/offsets 형식이 올바르지 않습니다")
    offsets = {str(role): int(offset) for role, offset in offsets.items()}
    validate_port_base(default_base, offsets)
    services = services_document.get("services")
    compose_services = {
        role: str(services[role]["compose_service"])
        for role in offsets
        if isinstance(services, dict) and isinstance(services.get(role), dict)
        and services[role].get("compose_service")
    }
    env = os.environ if environment is None else environment
    base = parse_port_base(env.get(PORT_BASE_ENV, ""), offsets, default_base)
    return PortNamespace(base, default_base, offsets, compose_services)


def load_port_namespace(
    root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> PortNamespace:
    """`environment`가 없으면 현재 프로세스 환경을 읽는다.

    컨테이너 프로세스는 `.env`가 환경변수로 주입되므로 기본값을 사용한다.
    Host 쪽 스크립트는 `.env`를 읽은 값을 명시적으로 넘긴다.
    """
    project_root = resolve_project_root(root, required_paths=("configs/services.yaml",))
    document = load_yaml_mapping(project_root / "configs" / "services.yaml")
    return port_namespace_from_services(document, environment)
