#!/usr/bin/env python3
"""프로젝트 소유 Port Namespace를 단일 명령으로 검토하고 변경한다."""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "services.yaml"

# 내부/Host 포트를 가진 프로젝트 서비스만 이 정책에 속한다.
# 서드파티 엔진의 고유 포트(예: Grafana 3000, DCGM 9400)는 제외한다.
REQUIRED_OFFSETS = {
    "gateway": 0,
    "main_llm_vllm": 1,
    "embedding_vllm": 2,
    "embedding_ko_vllm": 3,
    "prompt_injection_detector_runtime": 4,
    "risk_signal_service": 5,
    "grafana": 10,
    "mlx_metrics_exporter": 16,
    "team_api_proxy": 80,
}
INTERNAL_PORT_SERVICES = (
    "gateway", "main_llm_vllm", "embedding_vllm",
    "embedding_ko_vllm", "prompt_injection_detector_runtime",
    "risk_signal_service",
)
HOST_PORT_SERVICES = ("gateway", "risk_signal_service", "grafana")
LEGACY_ENV_PORTS = {"GATEWAY_PORT": (9400, 0), "RISK_SIGNAL_SERVICE_PORT": (9405, 5), "GRAFANA_PORT": (9411, 10)}
# v1(94xx)의 원래 역할·포트 배치다. 현재 Namespace와는 별도로 이관 입력으로만 읽는다.
LEGACY_RUNTIME_PORT_OFFSETS = {9400: 0, 9401: 1, 9402: 2, 9406: 3,
                               9403: 4, 9405: 5, 9411: 10, 9416: 16, 9480: 80}
GENERATED = (
    "ops/prometheus/prometheus.yml",
    "ops/prometheus/prometheus.macos-metal.yml",
    "specs/openapi.gateway.yaml",
    "specs/openapi.risk-signal-service.yaml",
    "docs/reference/api_reference.md",
    "docs/reference/openai_compatibility.md",
    "specs/schemas/model_list_response.schema.json",
)


def read_policy(root: Path) -> tuple[int, dict[str, int]]:
    doc = yaml.safe_load((root / "configs/services.yaml").read_text(encoding="utf-8"))
    policy = doc.get("port_namespace")
    if not isinstance(policy, dict):
        raise ValueError("configs/services.yaml에 port_namespace가 없습니다")
    base = policy.get("base")
    offsets = policy.get("offsets")
    if not isinstance(base, int) or not isinstance(offsets, dict):
        raise ValueError("port_namespace.base/offsets 형식이 올바르지 않습니다")
    if offsets != REQUIRED_OFFSETS:
        raise ValueError("지원되지 않는 Port Namespace offset 정책입니다")
    services = doc.get("services", {})
    for name in INTERNAL_PORT_SERVICES:
        actual = int(services[name]["container_port"])
        expected = base + offsets[name]
        if actual != expected:
            raise ValueError(f"{name}.container_port={actual}, 정책값={expected}; 설정 불일치")
    for name in HOST_PORT_SERVICES:
        actual = int(services[name]["default_host_port"])
        expected = base + offsets[name]
        if actual != expected:
            raise ValueError(f"{name}.default_host_port={actual}, 정책값={expected}; 설정 불일치")
    return base, offsets


def assert_base(value: int) -> None:
    if value < 1100 or value % 100 != 0 or value + max(REQUIRED_OFFSETS.values()) > 65535:
        raise ValueError("BASE는 1024 이상인 100 단위의 포트 대역 시작 번호여야 합니다")


def port_mapping(old: int, new: int, offsets: dict[str, int]) -> dict[int, int]:
    return {old + offset: new + offset for offset in set(offsets.values()) if old != new}


def managed_path(path: str) -> bool:
    if path in {"Dockerfile", "README.md", ".env.compose.example", ".env.local.example", "Makefile"}:
        return True
    if path.endswith((".lock", ".png", ".jpg", ".gif", ".svg", ".map", ".min.js")):
        return False
    if path.startswith(("docs/adr/", "docs/resources/", "assets/")):
        return False
    if path in {"CHANGELOG.md", "scripts/config/ports.py", "tests/unit/test_port_namespace.py"} or path.startswith("src/ai_model_serving/static/"):
        # Browser 배포 파일은 Vite가 생성하는 산출물이다. 문자열 치환하지 않는다.
        return False
    return path.startswith((
        "configs/", "ops/compose/", "ops/access/", "ops/prometheus/",
        "ops/perf/", "scripts/", "src/", "tests/",
        "specs/", "docs/", "ui/control-plane/src/", "ui/control-plane/tests/",
    ))


def replace_ports(content: str, mapping: dict[int, int], path: str) -> str:
    if not mapping:
        return content

    # 프로젝트 소유 포트와 같은 숫자를 사용하는 upstream DCGM은 변경하지 않는다.
    guarded: dict[str, str] = {}
    if path == "configs/services.yaml":
        match = re.search(r"(?ms)^  dcgm_exporter:\n.*?(?=^  [a-z_]+:|\Z)", content)
        if match:
            guarded["__UPSTREAM_DCGM_BLOCK__"] = match.group()
            content = content[:match.start()] + "__UPSTREAM_DCGM_BLOCK__" + content[match.end():]
    if path == "ops/compose/full-stack.private-network.yaml":
        match = re.search(r"(?ms)^  dcgm-exporter:\n.*?(?=^  [a-z][a-z0-9-]*:|\Z)", content)
        if match:
            guarded["__UPSTREAM_DCGM_BLOCK__"] = match.group()
            content = content[:match.start()] + "__UPSTREAM_DCGM_BLOCK__" + content[match.end():]
    if path.startswith("ops/prometheus/"):
        content = re.sub(r"dcgm-exporter:9400\b", "__UPSTREAM_DCGM_TARGET__", content)
        guarded["__UPSTREAM_DCGM_TARGET__"] = "dcgm-exporter:9400"
    # 문서의 DCGM Exporter도 자체 내부 포트 9400을 사용한다.
    # 프로젝트 BASE를 다시 9400으로 내린 후 상향 변경해도 따라 움직이면 안 된다.
    if path == "docs/04_runtime_modes.md":
        content = content.replace("| `dcgm-exporter` | `9400` |",
                                  "| `dcgm-exporter` | __UPSTREAM_DCGM_PORT__ |")
        guarded["__UPSTREAM_DCGM_PORT__"] = "`9400`"
    if path == "docs/appendix.md":
        content = content.replace("| DCGM Exporter | `dcgm-exporter` | `9400` |",
                                  "| DCGM Exporter | `dcgm-exporter` | __UPSTREAM_DCGM_PORT__ |")
        guarded["__UPSTREAM_DCGM_PORT__"] = "`9400`"
    if path == "docs/03_system_components.md":
        content = content.replace("| **DCGM Exporter** | `9400` |",
                                  "| **DCGM Exporter** | __UPSTREAM_DCGM_PORT__ |")
        guarded["__UPSTREAM_DCGM_PORT__"] = "`9400`"

    expr = re.compile(r"(?<![0-9])(?:" + "|".join(map(str, sorted(mapping, reverse=True))) + r")(?![0-9])")
    content = expr.sub(lambda m: str(mapping[int(m.group())]), content)
    for token, original in guarded.items():
        content = content.replace(token, original)
    return content


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    )
    return sorted(p for p in result.stdout.decode("utf-8").split("\0") if p and managed_path(p))


def env_changes(content: str, old_base: int, new_base: int) -> str:
    # 운영자 소유의 사용자 지정 포트는 자동 덮어쓰지 않는다.
    # 94xx에서 새 체크아웃의 96xx로 업데이트한 환경만 명시적으로 이관한다.
    # 레거시 94xx 기본값은 새 대역으로 직접 이관할 수 있다.
    # 현재 Namespace와 숫자가 겹치는 경우에는 현재 역할 배치를 우선한다.
    mapping = {port: new_base + offset for port, offset in LEGACY_RUNTIME_PORT_OFFSETS.items()}
    mapping.update(port_mapping(old_base, new_base, REQUIRED_OFFSETS))
    result: list[str] = []
    for line in content.splitlines(keepends=True):
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*?)(\r?\n)?", line)
        if not match:
            result.append(line)
            continue
        name, value, ending = match.groups()
        if name in LEGACY_ENV_PORTS:
            legacy, offset = LEGACY_ENV_PORTS[name]
            expected = old_base + offset
            target = new_base + offset
            if not value.isdigit():
                raise ValueError(f".env의 {name}은 정수 포트여야 합니다")
            old_value = int(value)
            if old_value in (expected, target, legacy):
                value = str(target)
            elif old_base != new_base:
                raise ValueError(f".env의 {name}={old_value}은 운영자 지정 포트이므로 자동 변경하지 않습니다")
            # 변경 요청 자체가 없는 경우에는 운영자 override를 그대로 둔다.
        elif name.endswith(("_BASE_URL", "_URL")):
            # 프로젝트 관리 서비스의 Docker DNS URL만 변경한다.
            if re.search(r"//(?:gateway|main-llm-vllm|embedding-vllm|embedding-ko-vllm|prompt-injection-detector-runtime|risk-signal-service):", value):
                value = replace_ports(value, mapping, ".env")
        result.append(f"{name}={value}{ending or ''}")
    return "".join(result)


def atomic_write(path: Path, content: bytes) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".port-change-", delete=False) as temporary:
        temp_path = Path(temporary.name)
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def preflight_bind(new_base: int, old_base: int) -> list[str]:
    warnings: list[str] = []
    if new_base == old_base:
        return warnings
    for service_name in ("gateway", "grafana"):
        port = new_base + REQUIRED_OFFSETS[service_name]
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                warnings.append(f"{service_name} 신규 포트 {port}: 현재 사용 중일 수 있습니다")
    return warnings


def run(root: Path, new_base: int, yes: bool, *, validate: bool = True) -> int:
    assert_base(new_base)
    old_base, offsets = read_policy(root)
    mapping = port_mapping(old_base, new_base, offsets)
    changes: dict[Path, bytes] = {}
    for name in tracked_paths(root):
        path = root / name
        try:
            before = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        after = replace_ports(before, mapping, name)
        if before != after:
            changes[path] = after.encode("utf-8")
    env_path = root / ".env"
    if env_path.is_file():
        before = env_path.read_text(encoding="utf-8")
        after = env_changes(before, old_base, new_base)
        if before != after:
            changes[env_path] = after.encode("utf-8")
    if not changes:
        print(f"[ports] BASE={new_base}: 이미 적용된 상태입니다")
        return 0

    print(f"[ports] Port Namespace: {old_base} → {new_base}")
    for name, offset in offsets.items():
        print(f"  {name:37s} {old_base + offset} → {new_base + offset}")
    conflicts = preflight_bind(new_base, old_base)
    if conflicts:
        for conflict in conflicts:
            print(f"[ports] 충돌: {conflict}", file=sys.stderr)
        return 2
    print(f"[ports] 변경 대상 {len(changes)}개 파일; 런타임 적용은 make up이 담당합니다")
    # 확인 프롬프트 사이에 다른 운영자가 수정한 파일을 덮어쓰지 않는다.
    planned_originals = {path: path.read_bytes() for path in changes}
    if not yes:
        if not sys.stdin.isatty():
            print("[ports] 비대화형 환경에서는 YES=1을 지정해야 합니다", file=sys.stderr)
            return 2
        if input("설정 변경을 적용할까요? [y/N]: ").strip().lower() not in ("y", "yes"):
            print("[ports] 취소했습니다")
            return 0

    if any(path.read_bytes() != original for path, original in planned_originals.items()):
        raise ValueError("포트 변경 계획 이후 파일이 수정됐습니다. 명령을 다시 실행하세요")
    originals: dict[Path, bytes] = planned_originals
    for name in GENERATED:
        path = root / name
        if path.is_file():
            originals.setdefault(path, path.read_bytes())

    console_dir = root / "src/ai_model_serving/static/control-plane"
    if validate and mapping and any(
        str(path.relative_to(root)).startswith("ui/control-plane/src/") for path in changes
    ):
        # Console 소스가 변경되면 Vite hash/manifest도 함께 갱신해야 한다.
        # 정적 JS를 숫자 치환하면 hash drift와 배포 UI 불일치가 발생한다.
        if not subprocess.run(["npm", "--version"], cwd=root, capture_output=True).returncode == 0:
            raise ValueError("Console 산출물 재생성에 Node.js/npm이 필요합니다")
        for file in console_dir.rglob("*"):
            if file.is_file():
                originals.setdefault(file, file.read_bytes())
        rebuild_console = True
    else:
        rebuild_console = False

    try:
        for path, data in changes.items():
            atomic_write(path, data)
        if validate:
            subprocess.run([sys.executable, "scripts/render_runtime_assets.py", "--write"], cwd=root, check=True)
            if rebuild_console:
                subprocess.run(["make", "console-build"], cwd=root, check=True)
            subprocess.run(["make", "validate"], cwd=root, check=True)
    except BaseException:
        if rebuild_console:
            for file in console_dir.rglob("*"):
                if file.is_file() and file not in originals:
                    file.unlink()
        for path, data in originals.items():
            atomic_write(path, data)
        print("[ports] 검증 실패: 설정을 기존 상태로 복구했습니다", file=sys.stderr)
        raise
    print(f"[ports] 적용 완료: BASE={new_base}. make up으로 반영하세요")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Port Namespace 일괄 변경")
    parser.add_argument("--base", type=int, required=True, help="프로젝트 Port Namespace 시작 번호")
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트만 건너뜀")
    args = parser.parse_args()
    try:
        return run(ROOT, args.base, args.yes)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[ports] 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
