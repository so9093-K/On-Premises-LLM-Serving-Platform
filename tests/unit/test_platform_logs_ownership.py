"""일반 Compose 설치의 진단 로그를 찾되 다른 checkout의 로그는 노출하지 않는다."""
from __future__ import annotations

import subprocess

from scripts.ops import platform_logs


def test_raw_gateway_logs_include_canonical_and_legacy_checkout_only(monkeypatch, capsys):
    root = platform_logs.ROOT
    inventory = {
        "canonical": (root / "ops/compose", "gateway"),
        "legacy": (root, "gateway"),
        "risk": (root / "ops/compose", "risk-signal-service"),
        "foreign": (root.parent / "other-checkout/ops/compose", "gateway"),
    }

    def docker(command, **kwargs):
        if command[1] == "ps":
            filters = [command[i + 1] for i, word in enumerate(command) if word == "--filter"]
            matches = []
            for name, (directory, service) in inventory.items():
                labels = {
                    f"label=com.docker.compose.project.working_dir={directory}",
                    f"label=com.docker.compose.service={service}",
                }
                if all(value in labels for value in filters):
                    matches.append(name)
            return subprocess.CompletedProcess(command, 0, "\n".join(matches))
        if command[1] == "inspect":
            return subprocess.CompletedProcess(command, 0, f"/{command[-1]}\n")
        assert command[1] == "logs"
        print(f"observed log: {command[-1]}")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(platform_logs.subprocess, "run", docker)
    assert platform_logs._raw_logs("gateway", tail=5, follow=False) == 0
    output = capsys.readouterr().out
    assert "observed log: canonical" in output
    assert "observed log: legacy" in output
    assert "foreign" not in output
    assert "risk" not in output
