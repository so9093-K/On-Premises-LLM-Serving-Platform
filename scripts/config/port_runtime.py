#!/usr/bin/env python3
"""배포 포트 대역을 Compose 실행 입력으로 투영한다.

Compose 보간 변수를 `KEY=VALUE`로 출력한다. `--prometheus`를 주면 현재 대역의 수집
대상을 해당 경로에 생성하고, 내용 digest를 `PROMETHEUS_CONFIG_DIGEST`로 함께 출력한다.
Compose는 이 digest label이 바뀐 Prometheus만 다시 만든다. 저장소 파일은 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ai_model_serving.configuration import load_yaml_mapping  # noqa: E402
from ai_model_serving.deployment_target import load_deployment_target  # noqa: E402
from ai_model_serving.domain import ModelRegistry  # noqa: E402
from ai_model_serving.monitoring_projection import (  # noqa: E402
    macos_metal_prometheus_config_document,
    prometheus_scrape_config_document,
)
from ai_model_serving.port_namespace import PortNamespace, load_port_namespace  # noqa: E402
from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file  # noqa: E402
from scripts.lib.atomic_file import atomic_write  # noqa: E402

_HEADER = (
    "# make up이 배포 포트 대역으로 생성한 {name}입니다. 직접 수정하지 마세요.\n"
    "# 원본: configs/monitoring.yaml, configs/services.yaml, .env의 PLATFORM_PORT_BASE\n"
)


def prometheus_document(namespace: PortNamespace, variant: str) -> dict:
    monitoring = load_yaml_mapping(ROOT / "configs/monitoring.yaml")
    services = load_yaml_mapping(ROOT / "configs/services.yaml")["services"]
    if variant == "macos-metal":
        target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "macos-metal-static")
        return macos_metal_prometheus_config_document(
            monitoring=monitoring,
            services=services,
            macos_runtime=load_yaml_mapping(ROOT / "configs/macos_mlx_runtime.yaml"),
            runtime_backend=target.runtime_backend,
            port_namespace=namespace,
        )
    registry = ModelRegistry(
        load_yaml_mapping(ROOT / "configs/model_catalog.yaml"),
        load_yaml_mapping(ROOT / "configs/model_serving.yaml"),
    )
    return prometheus_scrape_config_document(
        registry=registry, monitoring=monitoring, services=services, port_namespace=namespace
    )


def write_prometheus(namespace: PortNamespace, variant: str, output: Path) -> str:
    name = "prometheus.macos-metal.yml" if variant == "macos-metal" else "prometheus.yml"
    body = yaml.dump(
        prometheus_document(namespace, variant),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    content = (_HEADER.format(name=name) + body).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file() or output.read_bytes() != content:
        atomic_write(output, content)
    # Prometheus는 non-root로 실행되므로 bind mount된 설정 파일을 읽을 수 있어야 한다.
    output.chmod(0o644)
    return hashlib.sha256(content).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--prometheus", type=Path, help="생성할 Prometheus 설정 경로")
    parser.add_argument("--variant", choices=("linux", "macos-metal"), default="linux")
    args = parser.parse_args(argv)
    try:
        values = load_strict_env_file(args.env_file) if args.env_file.is_file() else {}
        namespace = load_port_namespace(ROOT, values)
        variables = namespace.compose_variables(values)
        if args.prometheus is not None:
            variables["PROMETHEUS_CONFIG_DIGEST"] = write_prometheus(
                namespace, args.variant, args.prometheus
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ports] 오류: {exc}", file=sys.stderr)
        return 2
    for key, value in variables.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
