from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.validation.runtime.live_checks import provisioned_dashboard_uids

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_expected_dashboards_follow_grafana_mounts_and_json_uids(tmp_path: Path) -> None:
    # 파일 이름과 uid가 다르고, 저장소에는 있지만 이 target이 mount하지 않는 Dashboard가
    # 있어도 기대값은 "mount한 파일의 JSON uid"여야 한다.
    _write(tmp_path / "ops/grafana/dashboards/mounted_file.json", json.dumps({"uid": "mounted-uid"}))
    _write(tmp_path / "ops/grafana/dashboards/other_target_only.json", json.dumps({"uid": "other"}))
    _write(
        tmp_path / "ops/compose/full-stack.private-network.yaml",
        "services:\n"
        "  grafana:\n"
        "    volumes:\n"
        "    - ../grafana/dashboards/mounted_file.json:/var/lib/grafana/dashboards/mounted_file.json:ro\n"
        "    - ../grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro\n",
    )

    assert provisioned_dashboard_uids(tmp_path) == ["mounted-uid"]


def test_full_stack_home_dashboard_is_a_provisioned_mount() -> None:
    compose_path = ROOT / "ops/compose/full-stack.private-network.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    grafana = compose["services"]["grafana"]
    home_path = grafana["environment"]["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"]

    source = next(
        str(volume).split(":", 1)[0]
        for volume in grafana["volumes"]
        if str(volume).split(":")[1] == home_path
    )
    dashboard = json.loads((compose_path.parent / source).resolve().read_text(encoding="utf-8"))

    assert dashboard["uid"] in provisioned_dashboard_uids(ROOT)
