from __future__ import annotations

import pytest
import shutil

from scripts.validation.governance import vllm_image as governance
from scripts.lib.source_provenance import input_paths


@pytest.fixture
def runtime_source(tmp_path, monkeypatch):
    root = governance.ROOT
    for name in input_paths("vllm-unified"):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, destination)
    monkeypatch.setattr(governance, "ROOT", tmp_path)
    monkeypatch.setattr(governance, "_DOCKERFILE", tmp_path / "ops/images/vllm-unified/Dockerfile")
    return tmp_path


def test_runtime_build_validation_allows_missing_and_edited_distribution_files(runtime_source):
    """소스 복사본의 LICENSE·NOTICE 유무가 실행 설정 검증을 막지 않는다."""
    governance.validate_vllm_unified_build_inputs()
    for name in ("LICENSE", "NOTICE"):
        (runtime_source / name).write_text("local distribution text\n")
    governance.validate_vllm_unified_build_inputs()


@pytest.mark.parametrize("missing", ["ops/images/vllm-unified/requirements.media.lock",
                                    "ops/patches/apply_gemma4_multimodal_patches.py"])
def test_runtime_build_validation_rejects_missing_execution_files(runtime_source, missing):
    (runtime_source / missing).unlink()
    with pytest.raises(SystemExit, match="source manifest path is not a file"):
        governance.validate_vllm_unified_build_inputs()


def test_runtime_build_validation_rejects_untracked_copy_inputs(runtime_source):
    with governance._DOCKERFILE.open("a") as stream:
        stream.write("\nCOPY scripts/new-runtime.py /runtime.py\n")
    with pytest.raises(SystemExit, match="include every local Dockerfile COPY source"):
        governance.validate_vllm_unified_build_inputs()


def _build_config(pin: str = "0.25.1") -> dict:
    return {"compatibility_pins": {"vllm": pin}}


def test_security_posture_review_tracks_current_engine_pin(monkeypatch) -> None:
    monkeypatch.setattr(governance, "read_yaml", lambda _path: _build_config())
    monkeypatch.setattr(
        governance,
        "_read_security_posture",
        lambda: (
            "> Security review contract: `engine=0.25.1`, "
            "`reviewed_at=2026-09-21`.\n"
        ),
    )

    governance.validate_vllm_security_posture_review()


def test_security_posture_review_rejects_stale_engine_pin(monkeypatch) -> None:
    monkeypatch.setattr(governance, "read_yaml", lambda _path: _build_config("0.29.0"))
    monkeypatch.setattr(
        governance,
        "_read_security_posture",
        lambda: (
            "> Security review contract: `engine=0.25.1`, "
            "`reviewed_at=2026-09-21`.\n"
        ),
    )

    with pytest.raises(SystemExit, match="security posture review is stale"):
        governance.validate_vllm_security_posture_review()


def test_security_posture_review_requires_one_contract_line(monkeypatch) -> None:
    monkeypatch.setattr(governance, "read_yaml", lambda _path: _build_config())
    monkeypatch.setattr(governance, "_read_security_posture", lambda: "# no review marker\n")

    with pytest.raises(SystemExit, match="exactly one review contract line"):
        governance.validate_vllm_security_posture_review()


def test_security_posture_review_rejects_invalid_review_date(monkeypatch) -> None:
    monkeypatch.setattr(governance, "read_yaml", lambda _path: _build_config())
    monkeypatch.setattr(
        governance,
        "_read_security_posture",
        lambda: (
            "> Security review contract: `engine=0.25.1`, "
            "`reviewed_at=2026-02-30`.\n"
        ),
    )

    with pytest.raises(SystemExit, match="valid ISO date"):
        governance.validate_vllm_security_posture_review()
