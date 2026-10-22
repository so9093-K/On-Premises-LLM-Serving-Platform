#!/usr/bin/env python3
"""프로젝트 소유 Port Namespace를 단일 명령으로 검토하고 변경한다."""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.atomic_file import atomic_write  # noqa: E402

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
GENERATED = (
    "ops/grafana/dashboards/service_overview.macos-metal.json",
    "ops/grafana/dashboards/request_log_explorer.macos-metal.json",
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
    assert_base(base)
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

    # Host Adapter와 추가 내부 Exporter도 정책값을 직접 따라야 한다.
    monitoring_path = root / "configs/monitoring.yaml"
    if monitoring_path.exists():
        monitoring = yaml.safe_load(monitoring_path.read_text(encoding="utf-8"))
        actual = int(monitoring["monitoring_stack"]["mlx_metrics_exporter"]["internal_port"])
        expected = base + offsets["mlx_metrics_exporter"]
        if actual != expected:
            raise ValueError(f"MLX Metrics 포트={actual}, 정책값={expected}; 설정 불일치")

    proxy_path = root / "ops/access/team-api.nginx.conf"
    if proxy_path.exists():
        nginx = proxy_path.read_text(encoding="utf-8")
        listen = re.search(r"(?m)^\s*listen 127\.0\.0\.1:(\d+);", nginx)
        expected = base + offsets["team_api_proxy"]
        if listen is None or int(listen.group(1)) != expected:
            raise ValueError(f"Nginx 팀원 Listener는 127.0.0.1:{expected}이어야 합니다")
        upstream_ports = re.findall(
            r"(?:proxy_set_header Host |proxy_pass http://)127\.0\.0\.1:(\d+)", nginx
        )
        if not upstream_ports or any(int(port) != base for port in upstream_ports):
            raise ValueError(f"Nginx Gateway upstream은 127.0.0.1:{base}이어야 합니다")
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
    if path in {"CHANGELOG.md", "scripts/config/ports.py", "tests/unit/test_port_namespace.py"} or path.startswith(("src/ai_model_serving/static/", "ui/control-plane/src/generated/")):
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
    # A requested destination in a command example is an operator choice, not
    # the current namespace. Preserve it across repeated/round-trip migrations.
    def keep_command_base(match: re.Match) -> str:
        token = f"__REQUESTED_BASE_{len(guarded)}__"
        guarded[token] = match.group()
        return token

    content = re.sub(r"\bBASE=\d+\b", keep_command_base, content)
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

    expr = re.compile(r"(?<![0-9A-Za-z_])(?:" + "|".join(map(str, sorted(mapping, reverse=True))) + r")(?![0-9A-Za-z_])")
    content = expr.sub(lambda m: str(mapping[int(m.group())]), content)
    for token, original in guarded.items():
        content = content.replace(token, original)
    return content


def source_paths(root: Path) -> list[str]:
    """Git index 없이 명시된 소스 영역의 일반 텍스트 파일만 선택한다."""
    root = root.resolve()
    roots = (
        "configs", "ops/compose", "ops/access", "ops/prometheus", "ops/perf",
        "scripts", "src", "tests", "specs", "docs",
        "ui/control-plane/src", "ui/control-plane/tests",
    )
    suffixes = {".py", ".sh", ".yaml", ".yml", ".json", ".md", ".ts", ".tsx",
                ".mjs", ".css", ".html", ".conf", ".toml", ".jinja", ".hujson"}
    excluded = {"node_modules", "__pycache__"}
    paths = {name for name in ("Dockerfile", "README.md", "Makefile", ".env.compose.example", ".env.local.example")
             if (root / name).is_file() and not (root / name).is_symlink()}

    def on_error(error: OSError) -> None:
        raise error

    for name in roots:
        directory = root / name
        parts = Path(name).parts
        if any((root / Path(*parts[:index])).is_symlink() for index in range(1, len(parts) + 1)):
            continue
        if not directory.is_dir():
            continue
        for parent, directories, files in os.walk(directory, onerror=on_error, followlinks=False):
            directories[:] = [d for d in directories if not d.startswith(".") and d not in excluded
                              and not d.endswith(".egg-info") and not (Path(parent) / d).is_symlink()
                              and managed_path((Path(parent) / d).relative_to(root).as_posix() + "/")]
            for filename in files:
                path = Path(parent) / filename
                if filename.startswith(".") or path.suffix not in suffixes or path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                if managed_path(relative):
                    paths.add(relative)
    return sorted(paths)


def env_changes(content: str, old_base: int, new_base: int) -> str:
    # 운영자 소유의 사용자 지정 포트는 자동 덮어쓰지 않는다.
    # 레거시 94xx 값도 서비스 역할로 구분해 명시적으로 이관한다.
    runtime_ports = {
        "gateway": (0, 9400), "main-llm-vllm": (1, 9401),
        "embedding-vllm": (2, 9402), "embedding-ko-vllm": (3, 9406),
        "prompt-injection-detector-runtime": (4, 9403), "risk-signal-service": (5, 9405),
    }
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
            parsed = urlsplit(value)
            role = runtime_ports.get(parsed.hostname or "")
            if parsed.scheme in {"http", "https"} and role:
                offset, legacy = role
                if parsed.port in {old_base + offset, new_base + offset, legacy}:
                    # Replace only the authority port, never path/query digits,
                    # credentials, or an external hostname embedded in a URL.
                    authority = parsed.netloc.rsplit(":", 1)[0] + f":{new_base + offset}"
                    value = urlunsplit(parsed._replace(netloc=authority))
        result.append(f"{name}={value}{ending or ''}")
    return "".join(result)


def preflight_bind(new_base: int, old_base: int, root: Path = ROOT) -> list[str]:
    warnings: list[str] = []
    if new_base == old_base:
        return warnings
    from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file

    env = load_strict_env_file(root / ".env") if (root / ".env").is_file() else {}
    for service_name in ("gateway", "grafana"):
        port = new_base + REQUIRED_OFFSETS[service_name]
        key = f"{service_name.upper()}_BIND_ADDR"
        address = os.environ.get(key, env.get(key, "0.0.0.0"))
        with socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET) as sock:
            try:
                sock.bind((address, port))
            except OSError:
                warnings.append(f"{service_name} 신규 포트 {port}: 현재 사용 중일 수 있습니다")
    return warnings


def run(root: Path, new_base: int, yes: bool, *, validate: bool = True, plan: bool = False) -> int:
    assert_base(new_base)
    old_base, offsets = read_policy(root)
    mapping = port_mapping(old_base, new_base, offsets)
    changes: dict[Path, bytes] = {}
    for name in source_paths(root):
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
    conflicts = preflight_bind(new_base, old_base, root)
    if conflicts:
        for conflict in conflicts:
            print(f"[ports] 충돌: {conflict}", file=sys.stderr)
        return 2
    print(f"[ports] 변경 대상 {len(changes)}개 파일; 런타임 적용은 make up이 담당합니다")
    print("[ports] 소스·설정·문서와 .env를 변경합니다. 실행 중 서비스는 make up 전까지 기존 포트를 사용합니다.")
    for path in sorted(changes):
        print(f"  {path.relative_to(root)}")
    if plan:
        print("[ports] 계획만 표시했습니다. 적용하려면 PLAN=1 없이 다시 실행하세요")
        return 0
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
    originals: dict[Path, bytes | None] = dict(planned_originals)
    for name in GENERATED:
        path = root / name
        originals.setdefault(path, path.read_bytes() if path.is_file() else None)

    console_dir = root / "src/ai_model_serving/static/control-plane"
    if validate and mapping and any(
        str(path.relative_to(root)).startswith("ui/control-plane/src/") for path in changes
    ):
        # Console 소스가 변경되면 Vite hash/manifest도 함께 갱신해야 한다.
        # 정적 JS를 숫자 치환하면 hash drift와 배포 UI 불일치가 발생한다.
        npm_hint = "Console 재생성에 Node.js/npm이 필요합니다. ui/control-plane/package.json의 지정 버전을 설치한 뒤 다시 실행하세요."
        try:
            npm = subprocess.run(["npm", "--version"], cwd=root, capture_output=True)
        except FileNotFoundError as exc:
            raise ValueError(npm_hint) from exc
        if npm.returncode != 0:
            raise ValueError(npm_hint)
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
            if mapping:
                # 서비스·코드·테스트가 함께 이동하므로 lint만으로는 충분하지 않다.
                subprocess.run(["make", "app-check"], cwd=root, check=True)
                if rebuild_console:
                    subprocess.run(["make", "console-check"], cwd=root, check=True)
            else:
                # 이미 적용된 Namespace에서 이전 .env만 갱신할 때는 설정 계약을 검증한다.
                subprocess.run(["make", "validate"], cwd=root, check=True)
    except BaseException:
        if rebuild_console:
            for file in console_dir.rglob("*"):
                if file.is_file() and file not in originals:
                    file.unlink()
        for path, data in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, data)
        print("[ports] 검증 실패: 설정을 기존 상태로 복구했습니다", file=sys.stderr)
        raise
    print(f"[ports] 파일 변경 완료: BASE={new_base}. 실행 중 서비스 반영은 make up이 필요합니다")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Port Namespace 일괄 변경")
    parser.add_argument("--base", type=int, required=True, help="프로젝트 Port Namespace 시작 번호")
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트만 건너뜀")
    parser.add_argument("--plan", action="store_true", help="변경 계획만 표시하고 파일과 서비스를 유지")
    args = parser.parse_args()
    try:
        return run(ROOT, args.base, args.yes, plan=args.plan)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"[ports] 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
