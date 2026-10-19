"""비공개 원격 접근 환경의 사전 조건이 실패할 때 적용을 안내하지 않는다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.access.remote_access import main, preflight


def write_env(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "ACCESS_PROFILE": "edge",
        "AUTH_MODE": "strict",
        "EXPOSURE_AUDIENCE": "local_only",
        "GATEWAY_BIND_ADDR": "127.0.0.1",
        "GRAFANA_BIND_ADDR": "127.0.0.1",
        "GATEWAY_PORT": "9400",
        "API_KEY_REQUIRED": "true",
        "ADMIN_API_KEY_REQUIRED": "true",
        "API_KEYS": "api-only-long-secret",
        "ADMIN_API_KEYS": "admin-only-long-secret",
    }
    values.update(overrides)
    path = tmp_path / ".env"
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    return path


def test_edge_loopback_and_separate_keys_allow_preflight(tmp_path):
    assert preflight(write_env(tmp_path)) == []


@pytest.mark.parametrize(("name", "value"), [
    ("ACCESS_PROFILE", "private"),
    ("AUTH_MODE", "local_open"),
    ("EXPOSURE_AUDIENCE", "private_lan"),
    ("GATEWAY_BIND_ADDR", "0.0.0.0"),
    ("GRAFANA_BIND_ADDR", "0.0.0.0"),
    ("GATEWAY_PORT", "9401"),
    ("API_KEY_REQUIRED", "false"),
    ("ADMIN_API_KEY_REQUIRED", "false"),
    ("API_KEYS", "change-me"),
    ("ADMIN_API_KEYS", "change-me"),
    ("ADMIN_API_KEYS", "api-only-long-secret"),
])
def test_remote_access_fails_closed_for_unsafe_env(tmp_path, name, value):
    assert preflight(write_env(tmp_path, **{name: value}))


def test_missing_and_ambiguous_env_are_rejected(tmp_path):
    assert preflight(tmp_path / "missing")
    path = write_env(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("ACCESS_PROFILE=local\n")
    assert preflight(path)


def test_plan_is_read_only_and_does_not_disclose_keys(monkeypatch, tmp_path, capsys):
    path = write_env(tmp_path)
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "plan", "--env-file", str(path)])

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("plan must not execute external commands")

    monkeypatch.setattr("scripts.access.remote_access.subprocess.run", unexpected_call)
    assert main() == 0
    output = capsys.readouterr().out
    assert "tailscale serve --bg" in output
    assert "api-only-long-secret" not in output
    assert "admin-only-long-secret" not in output
    assert "tailscale serve reset" in output  # 사용 금지 안내에만 등장한다.

def test_missing_grafana_bind_or_normalized_duplicate_key_fails(tmp_path):
    path = write_env(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("GRAFANA_BIND_ADDR=127.0.0.1\n", ""),
        encoding="utf-8",
    )
    assert preflight(path)
    assert preflight(write_env(tmp_path, API_KEYS="api-only-long-secret, admin-only-long-secret"))
