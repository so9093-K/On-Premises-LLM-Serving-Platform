from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai_model_serving.recent_traffic import RecentTrafficWindow, nearest_rank

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "specs/schemas/recent_traffic_response.schema.json").read_text(encoding="utf-8"))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _window(clock: FakeClock, **kwargs) -> RecentTrafficWindow:
    return RecentTrafficWindow(minimum_samples={"p50": 3, "p95": 5}, clock=clock, **kwargs)


def test_percentiles_use_nearest_rank_without_interpolation() -> None:
    # ceil(p x n)번째 값, 보간 없음.
    values = [float(v) for v in range(1, 21)]
    assert nearest_rank(values, 0.50) == 10.0
    assert nearest_rank(values, 0.95) == 19.0


def test_summary_withholds_percentiles_until_minimum_samples() -> None:
    clock = FakeClock()
    window = _window(clock)
    for seconds in (0.2, 0.4, 0.6, 0.8):
        window.record_completion_latency(seconds)

    latency = window.snapshot()["completion_latency_seconds"]

    assert latency == {"samples": 4, "p50": 0.4, "p95": None}


def test_summary_counts_only_the_recent_window() -> None:
    clock = FakeClock()
    window = _window(clock, window_seconds=60)
    window.record_request(200)
    window.record_request(503)
    clock.now += 61
    for status in (200, 200, 422, 500):
        window.record_request(status)

    summary = window.snapshot()

    assert summary["requests"] == {"total": 4, "client_errors": 1, "server_errors": 1}
    assert summary["observed_seconds"] == 60
    Draft202012Validator(SCHEMA).validate(summary)


def test_samples_are_bounded_under_bursty_load() -> None:
    clock = FakeClock()
    window = _window(clock, max_samples=100)
    for _ in range(10_000):
        window.record_request(200)

    assert window.snapshot()["requests"]["total"] == 100
