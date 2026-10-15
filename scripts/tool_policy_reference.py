"""Render the *default-profile illustration* in API Reference from canonical policy.

This is documentation projection, not another runtime capability authority.
Actual requests always use the active /v1/models response.
"""
from __future__ import annotations

BEGIN = "<!-- BEGIN GENERATED TOOL_POLICY -->"
END = "<!-- END GENERATED TOOL_POLICY -->"


def _row(label: str, profile_id: str, profiles: dict) -> str:
    policy = profiles["profiles"][profile_id]["gateway_policy"]["request_parameter_policy"]
    tools = policy["tool_calling"]
    if not tools["enabled"]:
        support = "비활성"
        modes = "—"
        parallel = "—"
    else:
        support = "지원"
        choice = tools["tool_choice"]
        modes = ", ".join(f"`{mode}`" for mode in choice["allowed"])
        if choice["allow_named"]:
            modes += ", named function"
        parallel = "허용" if tools["allow_parallel_tool_calls"] else "미지원"
    return f"| {label} (`{profile_id}`) | {support} | {modes} | {parallel} |"


def render_tool_policy_table(linux: dict, macos: dict) -> str:
    return "\n".join([
        "다음 표는 **저장소 기본 프로필**의 Tool Calling 예시입니다. 실제 요청 가능 범위는 "
        "활성 모델의 `GET /v1/models` 중 `request_parameters.tool_choice`와 `tools`를 확인하세요. "
        "지원하지 않는 선택 방식은 Gateway가 검증 오류로 거부합니다.",
        "",
        "| 대상 (기본 프로필) | Tool Calling | 허용 tool_choice | 병렬 Tool Calling |",
        "|---|---|---|---|",
        _row("Linux/CUDA", str(linux["default_profile"]), linux),
        _row("macOS/MLX", str(macos["default_profile"]), macos),
        "",
        "요청에 `tool_choice=required` 또는 named function choice를 쓸 수 있는지는 "
        "**엔진 전체 버전**이 아니라 **해당 활성 프로필의 공개 정책**에 따라 결정합니다.",
    ])


def project_tool_policy_section(document: str, linux: dict, macos: dict) -> str:
    if document.count(BEGIN) != 1 or document.count(END) != 1:
        raise ValueError("API Reference must contain one generated tool-policy boundary")
    before, rest = document.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    return before + BEGIN + "\n" + render_tool_policy_table(linux, macos) + "\n" + END + after
