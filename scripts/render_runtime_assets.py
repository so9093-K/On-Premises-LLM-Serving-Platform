#!/usr/bin/env python3
"""Source configuration과 runtime API에서 정적 배포 artifact를 생성한다.

생성 대상:
  ops/grafana/dashboards/service_overview.macos-metal.json
  ops/grafana/dashboards/request_log_explorer.macos-metal.json
  specs/schemas/model_list_response.schema.json
  specs/openapi.gateway.yaml
  docs/reference/openai_compatibility.md
  docs/reference/api_reference.md (Tool Calling 생성 구간)
  specs/openapi.risk-signal-service.yaml

생성 제외 대상:
  Prometheus 설정:
    수집 대상 포트는 배포의 PLATFORM_PORT_BASE를 따른다. make up이 실행할 때
    scripts/config/port_runtime.py로 .runtime/prometheus/에 생성한다.
  compose 파일 (full-stack.private-network.yaml):
    compose 파일에는 registry에서 파생할 수 없는 보일러플레이트가 있다
    (gateway env, prometheus secret, grafana env, healthcheck 등). PyYAML
    round-trip은 주석과 env placeholder를 유실한다.
    compose vLLM command drift는 make validate가
    validate_vllm_compose.py로 별도 검증한다.

Usage:
  python scripts/render_runtime_assets.py           # dry-run (drift 보고만, exit 0)
  python scripts/render_runtime_assets.py --check   # drift 있으면 exit 1
  python scripts/render_runtime_assets.py --write   # 모든 생성 artifact 파일에 쓰기
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from ai_model_serving.configuration import load_yaml_mapping  # noqa: E402
from ai_model_serving.domain import ModelRegistry  # noqa: E402
from ai_model_serving.deployment_target import load_deployment_target  # noqa: E402
from scripts.openapi_assets import build_generated_openapi, render_static_openapi  # noqa: E402
from scripts.openai_compatibility import render as render_openai_compatibility  # noqa: E402
from scripts.tool_policy_reference import project_tool_policy_section  # noqa: E402

# ── loaders ────────────────────────────────────────────────────────────────────

def _load_sources(root: Path) -> tuple[ModelRegistry, dict[str, Any]]:
    registry = ModelRegistry(
        load_yaml_mapping(root / "configs/model_catalog.yaml"),
        load_yaml_mapping(root / "configs/model_serving.yaml"),
    )
    return registry, load_yaml_mapping(root / "configs/macos_mlx_runtime.yaml")


# ── renderers ──────────────────────────────────────────────────────────────────

def render_model_list_schema_json(registry: ModelRegistry) -> str:
    doc = registry.model_list_schema_document()
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _strip_yaml_comments(text: str) -> str:
    """YAML 헤더 comment (#로 시작하는 줄)를 제거한다. inline comment는 대상 아님."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


def compare_artifact(path: Path, expected: str) -> bool:
    """현재 파일과 expected를 semantic하게 비교한다 (comment 차이 무시).

    YAML: yaml.safe_load로 파싱 후 Python dict 비교 (필드 순서 무시).
    JSON: json.loads로 파싱 후 비교 (whitespace 무시).
    기타: 문자열 직접 비교.
    """
    if not path.exists():
        return False
    actual = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(actual) == json.loads(expected)
        except Exception:
            return actual == expected
    if suffix in {".yaml", ".yml"}:
        try:
            return yaml.safe_load(_strip_yaml_comments(actual)) == yaml.safe_load(
                _strip_yaml_comments(expected)
            )
        except Exception:
            return actual == expected
    return actual == expected


# ── artifact map ───────────────────────────────────────────────────────────────

def render_macos_dashboard(root: Path, name: str) -> str:
    """공통 개요를 재사용하되 실제로 Provision된 Dashboard에만 연결한다."""
    dashboard = json.loads((root / f"ops/grafana/dashboards/{name}.json").read_text(encoding="utf-8"))
    target = load_deployment_target(root / "configs/deployment_targets.yaml", "macos-metal-static")
    available: set[str] = set()
    for compose_path in target.compose_files:
        compose = load_yaml_mapping(root / compose_path)
        grafana = compose.get("services", {}).get("grafana", {})
        for volume in grafana.get("volumes", []):
            if not isinstance(volume, str):
                continue
            source, _, destination = volume.partition(":")
            if "/var/lib/grafana/dashboards/" not in destination or not source.endswith(".json"):
                continue
            # Compose 상대 경로는 첫 번째 Compose 파일을 기준으로 해석한다.
            path = (root / target.compose_files[0]).parent / source
            template = path.with_name(path.name.replace(".macos-metal", ""))
            available.add(json.loads(template.read_text(encoding="utf-8"))["uid"])
    dashboard["links"] = [
        link for link in dashboard["links"]
        if not link.get("url", "").startswith("/d/")
        or link["url"].removeprefix("/d/").split("/")[0] in available
    ]
    return json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n"


def get_artifacts(
    registry: ModelRegistry,
    macos_runtime: dict[str, Any],
    root: Path,
) -> list[tuple[Path, str]]:
    """(파일 경로, expected 내용) 목록을 반환한다."""
    openapi_docs, _ = build_generated_openapi()
    api_reference = root / "docs/reference/api_reference.md"
    projected_reference = project_tool_policy_section(
        api_reference.read_text(encoding="utf-8"),
        load_yaml_mapping(root / "configs/main_model_profiles.yaml"),
        macos_runtime,
    )
    return [
        (api_reference, projected_reference),
        *[
            (root / f"ops/grafana/dashboards/{name}.macos-metal.json", render_macos_dashboard(root, name))
            for name in ("service_overview", "request_log_explorer")
        ],
        (
            root / "specs/schemas/model_list_response.schema.json",
            render_model_list_schema_json(registry),
        ),
        (root / "specs/openapi.gateway.yaml", render_static_openapi(openapi_docs["gateway"])),
        (
            root / "specs/openapi.risk-signal-service.yaml",
            render_static_openapi(openapi_docs["risk-signal-service"]),
        ),
        (
            root / "docs/reference/openai_compatibility.md",
            render_openai_compatibility(),
        ),
    ]


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="프로젝트 Source of Truth에서 정적 배포 artifact를 생성/검증합니다."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write", action="store_true", help="생성 산출물을 실제 파일에 씁니다."
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="현재 파일과 expected를 비교하고 drift가 있으면 exit 1합니다.",
    )
    args = parser.parse_args()

    root = ROOT
    registry, macos_runtime = _load_sources(root)
    artifacts = get_artifacts(registry, macos_runtime, root)

    if args.write:
        for path, content in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(root)}")
        return 0

    # check 또는 dry-run 모드
    drifts: list[tuple[Path, str]] = []
    for path, expected in artifacts:
        if not compare_artifact(path, expected):
            drifts.append((path, expected))
    if drifts:
        print("Generated artifact drift detected:", file=sys.stderr)
        for path, expected in drifts:
            relative = str(path.relative_to(root))
            print(f"  {relative}", file=sys.stderr)
            actual = path.read_text(encoding="utf-8") if path.exists() else ""
            diff = list(
                difflib.unified_diff(
                    actual.splitlines(),
                    expected.splitlines(),
                    fromfile=relative,
                    tofile=f"{relative} (generated)",
                    lineterm="",
                )
            )
            for line in diff[:160]:
                print(f"    {line}", file=sys.stderr)
            if len(diff) > 160:
                print(
                    f"    ... diff truncated ({len(diff) - 160} more lines)",
                    file=sys.stderr,
                )
        print("Run: make render-runtime-assets  to update.", file=sys.stderr)
        if args.check:
            return 1
        # dry-run: drift 보고만 하고 exit 0
        return 0

    print("All generated artifacts are up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
