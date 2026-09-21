from __future__ import annotations

import pytest

from scripts.validation.governance import vllm_image as governance


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
