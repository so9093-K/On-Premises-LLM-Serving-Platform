from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ai_model_serving.auth_control import diagnose_auth
from tests.unit.gateway.helpers import settings

ROOT = Path(__file__).resolve().parents[2]


def test_local_only_diagnosis_rejects_non_loopback_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "local_only")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "0.0.0.0")

    base = settings()
    cfg = replace(
        base,
        security=replace(
            base.security,
            auth_mode="local_open",
            api_key_required=False,
            internal_service_auth_required=False,
        ),
    )
    findings = diagnose_auth(cfg, ROOT)

    assert any(finding.code == "LOCAL_ONLY_BIND_MISMATCH" for finding in findings)
    assert any(
        "GATEWAY_BIND_ADDR=127.0.0.1" in finding.message
        for finding in findings
        if finding.code == "LOCAL_ONLY_BIND_MISMATCH"
    )
