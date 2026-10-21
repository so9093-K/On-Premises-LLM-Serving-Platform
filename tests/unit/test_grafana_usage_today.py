"""조회 기간·서비스 범위·표시 단위의 일관성을 보호한다."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = json.loads((ROOT / "ops/grafana/dashboards/usage_today.json").read_text(encoding="utf-8"))
PANELS = {panel["id"]: panel for panel in DASHBOARD["panels"]}


def test_today_defaults_to_calendar_day_without_a_second_time_window() -> None:
    assert DASHBOARD["time"] == {"from": "now/d", "to": "now"}
    assert DASHBOARD["timezone"] == "browser"
    assert not any(variable["name"] == "window" for variable in DASHBOARD["templating"]["list"])
    assert "$window" not in json.dumps(DASHBOARD)


@pytest.mark.parametrize("panel_id", [2, 3, 6])
def test_gateway_totals_follow_selected_period_without_cross_service_counts(panel_id: int) -> None:
    target = PANELS[panel_id]["targets"][0]
    assert target["instant"] is True
    assert "increase(" in target["expr"] and "[$__range]" in target["expr"]
    assert 'service="gateway"' in target["expr"]
    # 수집 누락을 정상적인 0건으로 바꾸지 않는다.
    assert "or vector(0)" not in target["expr"]
    assert "timeFrom" not in PANELS[panel_id] and "timeShift" not in PANELS[panel_id]


def test_call_totals_and_call_rates_have_distinct_dimensions() -> None:
    assert PANELS[2]["fieldConfig"]["defaults"]["unit"] == "short"
    assert "sort_desc(" in PANELS[2]["targets"][0]["expr"]
    assert PANELS[5]["fieldConfig"]["defaults"]["unit"] == "reqps"
    assert "rate(" in PANELS[5]["targets"][0]["expr"]
    assert "[$__rate_interval]" in PANELS[5]["targets"][0]["expr"]


def test_gpu_endpoint_is_not_a_historical_average_or_vram_percentage() -> None:
    assert PANELS[1]["targets"][0]["instant"] is True
    assert PANELS[1]["targets"][0]["expr"] == "max(gpu_utilization_ratio)"
    assert PANELS[1]["fieldConfig"]["defaults"]["unit"] == "percentunit"
    assert PANELS[1]["options"]["graphMode"] == "none"
