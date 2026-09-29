from __future__ import annotations

from pathlib import Path

import pytest

from ai_model_serving.auth_control import diagnose_auth
from tests.unit.gateway.helpers import settings

ROOT = Path(__file__).resolve().parents[2]


def test_master_open_local_only_reports_bind_findings_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 이 경로는 host bind 주소를 읽는다. 예전에는 없는 legacy 인자를 넘겨 TypeError로 죽었다.
    monkeypatch.setenv("EXPOSURE_MODE", "master_open")
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "local_only")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "0.0.0.0")

    findings = diagnose_auth(settings(), ROOT)

    assert findings, "diagnosis must report the open master_open exposure"
    assert all(finding.code for finding in findings)
