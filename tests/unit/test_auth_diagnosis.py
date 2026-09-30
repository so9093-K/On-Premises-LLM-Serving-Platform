from __future__ import annotations

from pathlib import Path

import pytest

from ai_model_serving.auth_control import diagnose_auth
from tests.unit.gateway.helpers import settings

ROOT = Path(__file__).resolve().parents[2]


def test_private_local_only_diagnosis_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXPOSURE_MODE", "private_network")
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "local_only")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "0.0.0.0")

    findings = diagnose_auth(settings(), ROOT)

    assert findings
    assert all(finding.code for finding in findings)
