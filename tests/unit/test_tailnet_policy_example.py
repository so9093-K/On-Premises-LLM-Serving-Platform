"""Tailnet 예제의 최소 권한·실수 방지 계약을 정적으로 보호한다.

실제 Tailnet의 기존 ACL/Grants, 권한 적용 및 Serve 상태를 증명하지는 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

POLICY = Path(__file__).resolve().parents[2] / "ops" / "access" / "tailnet-policy.example.hujson"


def load_example() -> dict:
    # 예제의 주석은 별도 단독 행에만 둔다. 동적인 Tailscale Policy 파서는 아니다.
    lines = [
        line for line in POLICY.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    return json.loads("\n".join(lines))


def test_team_has_no_admin_or_broad_network_grant():
    policy = load_example()
    assert policy["grants"] == [
        {
            "src": ["group:llm-admins"],
            "dst": ["tag:llm-server"],
            "ip": ["tcp:443", "tcp:8443"],
        },
        {
            "src": ["group:llm-team"],
            "dst": ["tag:llm-server"],
            "ip": ["tcp:8443"],
        },
    ]
    assert set(policy["groups"]["group:llm-admins"]).isdisjoint(
        policy["groups"]["group:llm-team"]
    )
    assert policy["tagOwners"]["tag:llm-server"] == ["group:llm-admins"]


def test_tailnet_policy_checks_team_and_admin_denial():
    policy = load_example()
    tests = {item["src"]: item for item in policy["tests"]}
    for port in (443, 9400, 9411, 22):
        assert f"tag:llm-server:{port}" in tests["teammate@example.com"]["deny"]
    assert "tag:llm-server:8443" in tests["teammate@example.com"]["accept"]
    assert "tag:llm-server:443" in tests["operator@example.com"]["accept"]
    assert "tag:llm-server:9400" in tests["operator@example.com"]["deny"]
