"""Guard operator-facing advice that can bypass config migration and docs authority."""
from __future__ import annotations

import ast
import re

from .common import ROOT, read_yaml


def validate_removed_env_key_guidance() -> None:
    """Removed persistent image refs may be mentioned in history, not prescribed at preflight."""
    removed = set(read_yaml("configs/env_contract.yaml")["removed_keys"])
    path = ROOT / "scripts/compose/preflight_compose.py"
    program = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for call in ast.walk(program):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "print":
            continue
        # Joined or adjacent string literal segments can be inspected without executing code.
        literals = " ".join(
            node.value for arg in call.args for node in ast.walk(arg)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        for key in removed:
            if re.search(rf"(?<![A-Z0-9_]){re.escape(key)}(?![A-Z0-9_])", literals):
                raise SystemExit(
                    f"{path.relative_to(ROOT)}: operator preflight message references removed "
                    f"persistent key {key}; guide users to the canonical replacement"
                )


def validate_operator_documentation() -> None:
    """Guard the Tool Calling documentation boundary against duplicate or stale assertions."""
    from scripts.tool_policy_reference import project_tool_policy_section

    path = ROOT / "docs/reference/api_reference.md"
    document = path.read_text(encoding="utf-8")
    try:
        projection = project_tool_policy_section(
            document,
            read_yaml("configs/main_model_profiles.yaml"),
            read_yaml("configs/macos_mlx_runtime.yaml"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"{path.relative_to(ROOT)}: invalid Tool Calling reference: {exc}") from exc
    if document != projection:
        raise SystemExit(
            f"{path.relative_to(ROOT)} Tool Calling documentation drifts from the active "
            "default profiles; run make render-runtime-assets"
        )
