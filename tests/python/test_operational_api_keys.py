"""키 교체 뒤에도 운영 도구는 활성 허용 목록으로 인증한다."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from scripts.config.setup_env import read_env_values, sync_env_keys

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("alias", ["revoked", "user-second"])
def test_sync_keeps_allowlists_and_aligns_only_revoked_aliases(tmp_path, capsys, alias):
    env = tmp_path / ".env"
    env.write_text(
        f"BUILD_PROFILE=local\nAPI_KEYS=user-first,user-second\nAPI_KEY={alias}\n"
        "ADMIN_API_KEYS=admin-first,admin-second\nADMIN_API_KEY=revoked-admin\n"
    )
    initial = env.read_bytes()
    assert sync_env_keys(env, dry_run=True) == 0
    assert env.read_bytes() == initial
    assert sync_env_keys(env) == 0
    values = read_env_values(env)
    assert values["API_KEYS"] == "user-first,user-second"
    assert values["ADMIN_API_KEYS"] == "admin-first,admin-second"
    assert values["API_KEY"] == ("user-first" if alias == "revoked" else alias)
    assert values["ADMIN_API_KEY"] == "admin-first"
    output = capsys.readouterr().out
    assert "user-first" not in output
    assert "admin-first" not in output


def test_shell_probe_uses_one_active_file_key_instead_of_stale_alias(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_KEYS=user-first, user-second\nAPI_KEY=revoked\n")
    result = subprocess.run(
        ["bash", "-c", 'source scripts/lib/load_env.sh; '
         'local_env_first_value "$1" API_KEYS API_KEY', "probe", str(env)],
        cwd=ROOT, env=os.environ | {"API_KEY": "stale-shell", "API_KEYS": "stale-list"},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "user-first"
