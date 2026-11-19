"""사용자 진입점의 인증·정적 파일과 외부 Listener의 소유권 경계를 보호한다."""
from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from ai_model_serving.admin_console import register_public_playground
from ai_model_serving.security import require_bearer_auth
from ai_model_serving.settings import SecuritySettings
from scripts.access import public_access


def test_playground_uses_user_key_and_only_projects_user_features():
    app = FastAPI()
    auth = require_bearer_auth(SecuritySettings(
        api_key_required=True, api_keys=frozenset({"user-key"}),
        internal_service_token="internal-key", admin_api_key_required=True,
        admin_api_keys=frozenset({"admin-key"}),
    ))
    register_public_playground(
        app, features=("chat", "risk", "runtime_control", "model_switching"),
        api_dependencies=[Depends(auth)],
    )
    with TestClient(app) as client:
        for key in (None, "invalid", "admin-key"):
            assert client.get("/playground/config.json", headers={
                "Authorization": f"Bearer {key}",
            } if key else {}).status_code == 401
        response = client.get("/playground/config.json", headers={"Authorization": "Bearer user-key"})
        assert response.json() == {"features": ["chat", "risk"]}
        assert response.headers["cache-control"] == "no-store"
        for path in ("/playground/", "/playground/chat", "/playground/embeddings", "/playground/risk"):
            page = client.get(path)
            assert page.status_code == 200
            assert "/admin/" not in page.text
            for asset in re.findall(r'(?:src|href)="(/playground/assets/[^\"]+)"', page.text):
                assert client.get(asset).status_code == 200
        for path in ("/playground/assets/missing.js", "/playground/assets/%2e%2e/owner.json", "/playground/admin/config"):
            assert client.get(path).status_code == 404


def test_short_credentials_block_publication_before_host_commands(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_KEYS=short-key\nADMIN_API_KEYS=" + "a" * 40 + "\n")
    with patch("scripts.access.remote_access.preflight", return_value=[]), patch.object(public_access, "_run") as run:
        with pytest.raises(RuntimeError, match="32자 이상"):
            public_access.start(env, tmp_path)
        run.assert_not_called()


@pytest.mark.parametrize(("values", "override", "access", "expected"), [
    ({}, None, None, True),
    ({"PUBLIC_ACCESS_ENABLED": "false"}, None, None, False),
    ({}, "off", None, False),
    ({}, None, "local", False),
    ({}, None, "private", False),
    ({"PUBLIC_ACCESS_ENABLED": "false"}, "on", "edge", True),
])
def test_public_access_defaults_and_explicit_local_choice(values, override, access, expected):
    assert public_access.sharing_enabled(values, override, access) is expected


def test_stop_preserves_foreign_or_changed_funnel(tmp_path):
    owner = {"checkout": str(public_access.ROOT), "host_port": "server.ts.net:8443", "target": "http://127.0.0.1:9480"}
    (tmp_path / "owner.json").write_text(json.dumps(owner))
    config = {
        "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
        "Web": {"server.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}},
        "AllowFunnel": {"server.ts.net:8443": True},
    }
    with patch.object(public_access, "_json_command", return_value=config), patch.object(public_access, "_run") as run:
        with pytest.raises(RuntimeError, match="설정이 변경"):
            public_access.stop(tmp_path)
        run.assert_not_called()
    assert (tmp_path / "owner.json").is_file()


def test_stop_only_disables_owned_8443_and_preserves_private_443(tmp_path):
    owner = {"checkout": str(public_access.ROOT), "host_port": "server.ts.net:8443", "target": "http://127.0.0.1:9480"}
    (tmp_path / "owner.json").write_text(json.dumps(owner))
    private = {"TCP": {"443": {"HTTPS": True}}}
    shared = {
        "TCP": {**private["TCP"], "8443": {"HTTPS": True}},
        "Web": {owner["host_port"]: {"Handlers": {"/": {"Proxy": owner["target"]}}}},
        "AllowFunnel": {owner["host_port"]: True},
    }
    with patch.object(public_access, "_json_command", side_effect=[shared, private]), patch.object(public_access, "_run") as run:
        public_access.stop(tmp_path)
        run.assert_called_once_with("tailscale", "funnel", "--https=8443", "off")
    assert not (tmp_path / "owner.json").exists()
