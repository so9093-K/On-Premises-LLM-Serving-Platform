#!/usr/bin/env python3
"""배포 포트 대역을 바꾼다.

포트 대역은 `.env`의 `PLATFORM_PORT_BASE` 하나가 정한다. 이 명령은 `.env`만 변경하며
소스·문서·생성물이나 실행 중인 서비스는 건드리지 않는다. 내부 포트·주소와 Prometheus
수집 대상은 `make up`이 같은 값에서 다시 계산해 적용한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ai_model_serving.deployment_target import load_deployment_target  # noqa: E402
from ai_model_serving.port_namespace import (  # noqa: E402
    HOST_PORT_OVERRIDES,
    PORT_BASE_ENV,
    PortNamespace,
    load_port_namespace,
)
from scripts.config.setup_env import (  # noqa: E402
    managed_endpoint_changes,
    parse_env_template,
    write_env,
)
from scripts.ops.host_ports import port_holders  # noqa: E402

ENV_PATH = ROOT / ".env"
_LOOPBACK = {"127.0.0.1", "localhost"}


@dataclass(frozen=True)
class PortPlan:
    old: PortNamespace
    new: PortNamespace
    changes: dict[str, tuple[str, str]]
    # 운영자가 직접 지정한 Host 포트. 대역을 바꿔도 유지한다.
    kept: dict[str, str]


def plan_port_change(values: dict[str, str], new_base: int) -> PortPlan:
    old = load_port_namespace(ROOT, values)
    target = {**values, PORT_BASE_ENV: str(new_base)}
    new = load_port_namespace(ROOT, target)
    changes: dict[str, tuple[str, str]] = {}
    if values.get(PORT_BASE_ENV, "").strip() != str(new_base):
        changes[PORT_BASE_ENV] = (values.get(PORT_BASE_ENV, ""), str(new_base))
    kept: dict[str, str] = {}
    for role, key in HOST_PORT_OVERRIDES.items():
        current = values.get(key, "").strip()
        if not current:
            continue
        defaults = {str(old.port(role)), str(new.port(role))}
        if current not in defaults:
            kept[key] = current
        elif current != str(new.port(role)):
            changes[key] = (current, str(new.port(role)))
    changes.update(managed_endpoint_changes(target))
    # app-only 프로세스의 loopback 주소도 같은 역할의 새 포트로 옮긴다.
    for key, value in values.items():
        parts = urlsplit(value) if key.endswith("_BASE_URL") else None
        if parts is None or key in changes or parts.hostname not in _LOOPBACK or parts.port is None:
            continue
        offset = parts.port - old.base
        if old.base != new.base and offset in old.offsets.values():
            host = parts.netloc.rsplit(":", 1)[0]
            changes[key] = (value, urlunsplit(parts._replace(netloc=f"{host}:{new.base + offset}")))
    return PortPlan(old, new, changes, kept)


def host_port_bindings(values: dict[str, str]) -> dict[str, tuple[int, str]]:
    """이 배포가 Host에 여는 포트. 이름 → (포트, bind 주소)."""
    namespace = load_port_namespace(ROOT, values)
    bindings = {
        "Gateway": (namespace.host_port("gateway", values), values.get("GATEWAY_BIND_ADDR") or "0.0.0.0"),
    }
    if values.get("BUILD_PROFILE") == "local":
        bindings["Risk"] = (
            namespace.host_port("risk_signal_service", values),
            values.get("RISK_SIGNAL_SERVICE_HOST") or "127.0.0.1",
        )
        return bindings
    target_id = values.get("DEPLOYMENT_TARGET", "").strip()
    monitoring = True
    if target_id:
        try:
            monitoring = load_deployment_target(
                ROOT / "configs/deployment_targets.yaml", target_id
            ).runs_monitoring_stack
        except (RuntimeError, ValueError):
            monitoring = True
    if monitoring:
        bindings["Grafana"] = (
            namespace.host_port("grafana", values), values.get("GRAFANA_BIND_ADDR") or "0.0.0.0"
        )
    return bindings


# app-only 모드에서 이 checkout이 실행한 Host 프로세스의 PID 파일이다(scripts/ops/up_services.sh).
_APP_ONLY_PID_FILES = {"Gateway": "run/gateway.pid", "Risk": "run/risk_signal_service.pid"}


def _app_only_process_running(name: str) -> bool:
    path = ROOT / _APP_ONLY_PID_FILES.get(name, "")
    try:
        os.kill(int(path.read_text(encoding="utf-8").strip()), 0)
    except (OSError, ValueError):
        return False
    return True


def host_port_conflicts(values: dict[str, str]) -> list[str]:
    """다른 프로그램이 사용 중인 Host 포트. 이 플랫폼 자신의 컨테이너·프로세스는 충돌이 아니다."""
    bindings = host_port_bindings(values)
    holders = port_holders(ROOT, {port: bind for port, bind in bindings.values()})
    app_only = values.get("BUILD_PROFILE") == "local"
    return [
        f"{name} {port}: {holders[port].describe(port)}"
        for name, (port, _) in bindings.items()
        if holders[port].kind == "container"
        or (holders[port].kind == "process" and not (app_only and _app_only_process_running(name)))
    ]


def suggest_free_base(values: dict[str, str], start: int, *, attempts: int = 10) -> int | None:
    """start 다음 대역부터 Host 포트가 모두 비어 있는 대역을 찾는다."""
    for base in range(start + 100, start + 100 * (attempts + 1), 100):
        try:
            plan = plan_port_change(values, base)
        except ValueError:
            return None
        # 운영자가 지정해 유지되는 Host 포트까지 포함해 실제로 열 포트를 검사한다.
        if not host_port_conflicts({**values, **{k: v for k, (_, v) in plan.changes.items()}}):
            return base
    return None


def render_plan(plan: PortPlan) -> list[str]:
    old, new = plan.old, plan.new
    lines = [f"[ports] 포트 대역 {old.base} → {new.base}"]
    for label, role, key in (("Gateway", "gateway", "GATEWAY_PORT"), ("Grafana", "grafana", "GRAFANA_PORT")):
        if key in plan.kept:
            lines.append(f"  {label:<10} {plan.kept[key]} (운영자 지정 포트 유지)")
        else:
            lines.append(f"  {label:<10} {old.port(role)} → {new.port(role)}")
    # 한글 라벨은 터미널에서 두 칸을 차지하므로 영문 라벨과 같은 10칸으로 맞춘다.
    lines.append(
        f"  내부 서비스 {old.base + 1}–{old.base + 5} → {new.base + 1}–{new.base + 5}"
        " (Compose 내부망, Host에 공개하지 않음)"
    )
    if plan.changes:
        lines.append(f"  {'.env':<10} {len(plan.changes)}개 값 변경 (포트 대역·Host 포트·내부 주소)")
    return lines


def apply_plan(env_path: Path, plan: PortPlan) -> None:
    lines, values = parse_env_template(env_path)
    for key, (_, after) in plan.changes.items():
        values[key] = after
    write_env(lines, values, env_path)


def change_port_base(
    env_path: Path,
    new_base: int,
    *,
    plan_only: bool = False,
    check_ports: bool = True,
    retry_hint: str = "make ports BASE={base}",
) -> int:
    """대역 변경을 계획·검사하고 `.env`에 기록한다. 실패하면 아무것도 바꾸지 않는다."""
    _, values = parse_env_template(env_path)
    plan = plan_port_change(values, new_base)
    if not plan.changes:
        print(f"[ports] 포트 대역 {new_base}: 이미 적용된 설정입니다")
        return 0
    for line in render_plan(plan):
        print(line)
    if check_ports:
        conflicts = host_port_conflicts({**values, **{k: v for k, (_, v) in plan.changes.items()}})
        if conflicts:
            print("[ports] 사용할 수 없는 Host 포트가 있어 변경하지 않았습니다:")
            for conflict in conflicts:
                print(f"  {conflict}")
            free = suggest_free_base(values, new_base)
            if free is not None:
                print(f"[ports] 비어 있는 대역: {retry_hint.format(base=free)}")
            return 2
    if plan_only:
        print("[ports] 계획만 표시했습니다. .env와 실행 중인 서비스는 그대로입니다.")
        return 0
    apply_plan(env_path, plan)
    print(f"[ports] .env에 포트 대역 {new_base}을 기록했습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 포트 대역 변경 (.env만 변경)")
    parser.add_argument("--base", type=int, required=True, help="포트 대역 시작 번호 (예: 9600)")
    parser.add_argument("--plan", action="store_true", help="변경 내용과 포트 충돌만 확인")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    if not args.env_file.is_file():
        print(
            "[ports] 아직 플랫폼 설정(.env)이 없습니다. 첫 설치는 대역을 함께 지정하세요:\n"
            f"  make up TARGET=<deployment-target> PORTS={args.base}",
            file=sys.stderr,
        )
        return 2
    try:
        result = change_port_base(args.env_file, args.base, plan_only=args.plan)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ports] 오류: {exc}", file=sys.stderr)
        return 2
    if result == 0 and not args.plan:
        print("[ports] 적용: make up  (Gateway·모델 컨테이너가 새 포트로 다시 만들어집니다)")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
