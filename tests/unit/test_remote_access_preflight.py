"""비공개 원격 접근 환경의 사전 조건이 실패할 때 적용을 안내하지 않는다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.access.remote_access import main, preflight
from ai_model_serving.access_profile import access_profile_env_values


def write_env(tmp_path: Path, **overrides: str) -> Path:
    values = {
        **access_profile_env_values("edge"),
        "GATEWAY_PORT": "9400",
        "API_KEYS": "api-only-long-secret",
        "API_KEY": "api-only-long-secret",
        "ADMIN_API_KEYS": "admin-only-long-secret",
        "ADMIN_API_KEY": "admin-only-long-secret",
        "INTERNAL_SERVICE_TOKEN": "internal-only-long-secret",
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
    ("ADMIN_ENDPOINTS_INTERNAL_ONLY", "true"),
    ("INTERNAL_SERVICE_AUTH_REQUIRED", "false"),
    ("FASTAPI_DOCS_ENABLED", "true"),
    ("INTERNAL_SERVICE_TOKEN", "change-me-internal"),
    ("API_KEYS", "change-me"),
    ("ADMIN_API_KEYS", "change-me"),
    ("ADMIN_API_KEYS", "api-only-long-secret"),
    ("API_KEY", "retired-team-api-key"),
    ("ADMIN_API_KEY", "retired-admin-key"),
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


def test_personal_plan_does_not_require_team_proxy(monkeypatch, tmp_path, capsys):
    path = write_env(tmp_path)
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "plan", "--purpose", "personal", "--env-file", str(path)])
    assert main() == 0
    text = capsys.readouterr().out
    assert "--https=443" in text
    assert "--https=8443" not in text
    assert "sudo nginx -t" not in text
    assert "api-only-long-secret" not in text


def test_team_plan_includes_api_only_proxy(monkeypatch, tmp_path, capsys):
    path = write_env(tmp_path)
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "plan", "--purpose", "team", "--env-file", str(path)])
    assert main() == 0
    text = capsys.readouterr().out
    assert "--https=8443 http://127.0.0.1:9480" in text
    assert "관리자" in text
    assert "sudo nginx -t" in text


def test_unconfigured_plan_shows_safe_access_migration(monkeypatch, tmp_path, capsys):
    path = write_env(tmp_path, ACCESS_PROFILE="local")
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "plan", "--env-file", str(path)])
    assert main() == 2
    text = capsys.readouterr().out
    assert "make up ACCESS=edge CONFIRM=access" in text
    assert "조치 필요" in text


def test_status_separates_observed_serve_and_unverified_external_access(monkeypatch, tmp_path, capsys):
    from subprocess import CompletedProcess
    import json
    from scripts.access import remote_access

    path = write_env(tmp_path)
    calls = []
    def fake_command(*args):
        calls.append(args)
        if args == ("status", "--json"):
            return CompletedProcess(args, 0, json.dumps({
                "BackendState": "Running", "Self": {"DNSName": "node.example.ts.net."}
            }))
        if args == ("serve", "status"):
            return CompletedProcess(args, 0,
                "https://node.example.ts.net\n|-- / proxy http://127.0.0.1:9400\n")
        if args == ("funnel", "status"):
            return CompletedProcess(args, 0, "No funnel config")
        raise AssertionError(args)
    monkeypatch.setattr(remote_access, "_tailscale_command", fake_command)
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "status", "--env-file", str(path)])
    assert main() == 0
    text = capsys.readouterr().out
    assert "https://node.example.ts.net/admin/console/" in text
    assert "표시된 설정에서 관측됨" in text
    assert "외부 기기 접근" in text
    assert "미검증" in text
    assert calls == [("status", "--json"), ("serve", "status"), ("funnel", "status")]


def test_status_fails_closed_on_disconnected_tailscale(monkeypatch, tmp_path, capsys):
    from subprocess import CompletedProcess
    from scripts.access import remote_access

    path = write_env(tmp_path)
    monkeypatch.setattr(remote_access, "_tailscale_command",
        lambda *args: CompletedProcess(args, 0, '{"BackendState":"NeedsLogin"}'))
    monkeypatch.setattr(sys, "argv", ["remote_access.py", "status", "--env-file", str(path)])
    assert main() == 1
    assert "연결되지 않음" in capsys.readouterr().out


def test_serve_mapping_must_match_port_and_backend():
    from scripts.access.remote_access import _serve_proxy_observed
    text = "https://node.example.ts.net:8443\n|-- / proxy http://127.0.0.1:9480\n"
    assert _serve_proxy_observed(text, 8443, "http://127.0.0.1:9480")
    assert not _serve_proxy_observed(text, 443, "http://127.0.0.1:9400")
