"""Evidence for operator-facing documentation and env migration advice contracts."""
from __future__ import annotations

import textwrap

import pytest

from scripts.tool_policy_reference import (
    BEGIN,
    END,
    project_tool_policy_section,
    render_tool_policy_table,
)
from scripts.validation.governance import operator_docs


def _profiles(allowed: list[str], *, enabled: bool = True, named: bool = False) -> dict:
    return {
        "default_profile": "example-profile",
        "profiles": {
            "example-profile": {
                "gateway_policy": {
                    "request_parameter_policy": {
                        "tool_calling": {
                            "enabled": enabled,
                            "tool_choice": {"allowed": allowed, "allow_named": named},
                            "allow_parallel_tool_calls": False,
                        }
                    }
                }
            }
        },
    }


def test_tool_policy_table_tracks_target_settings_not_static_brand_assumptions() -> None:
    linux = _profiles(["auto", "none"])
    macos = _profiles(["auto", "none", "required"], named=True)
    result = render_tool_policy_table(linux, macos)
    assert "| Linux/CUDA (`example-profile`) | 지원 | `auto`, `none` | 미지원 |" in result
    assert "| macOS/MLX (`example-profile`) | 지원 | `auto`, `none`, `required`, named function | 미지원 |" in result
    assert "GET /v1/models" in result
    linux["profiles"]["example-profile"]["gateway_policy"]["request_parameter_policy"]["tool_calling"]["enabled"] = False
    assert "| Linux/CUDA (`example-profile`) | 비활성 | — | — |" in render_tool_policy_table(linux, macos)


def test_tool_policy_document_fails_closed_on_missing_markers() -> None:
    linux, macos = _profiles(["auto"]), _profiles(["none"])
    with pytest.raises(ValueError, match="boundary"):
        project_tool_policy_section("no marker", linux, macos)


def test_tool_policy_projection_rewrites_stale_snapshot_without_other_doc_changes() -> None:
    linux, macos = _profiles(["auto"]), _profiles(["auto", "required"], named=True)
    original = f"# API Reference\n\n{BEGIN}\nold snapshot\n{END}\n\n## Other\n"
    result = project_tool_policy_section(original, linux, macos)
    assert "old snapshot" not in result
    assert result.startswith("# API Reference")
    assert result.endswith("## Other\n")
    assert result == project_tool_policy_section(result, linux, macos)


def test_preflight_removed_key_guidance_detects_actionable_old_image_ref(tmp_path, monkeypatch) -> None:
    source = tmp_path / "scripts" / "compose"
    source.mkdir(parents=True)
    file = source / "preflight_compose.py"
    file.write_text(
        textwrap.dedent('''
        def run():
            print("build a RISK_VLLM_IMAGE to fix this issue")
        '''),
        encoding="utf-8",
    )
    monkeypatch.setattr(operator_docs, "ROOT", tmp_path)
    monkeypatch.setattr(
        operator_docs,
        "read_yaml",
        lambda _path: {"removed_keys": {"RISK_VLLM_IMAGE": "obsolete"}},
    )
    with pytest.raises(SystemExit, match="RISK_VLLM_IMAGE"):
        operator_docs.validate_removed_env_key_guidance()
    file.write_text(
        'print("set VLLM_IMAGE instead; SKIP_RISK_VLLM_IMAGE_CONFIG_CHECK=1 is for local checks")\n',
        encoding="utf-8",
    )
    operator_docs.validate_removed_env_key_guidance()


def test_current_repository_tool_policy_reference_is_in_sync() -> None:
    # Runtime governance catches this too; this test describes the documentation contract.
    operator_docs.validate_operator_documentation()
