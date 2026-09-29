"""Gateway가 직접 집계하는 최근 공개 API 트래픽 요약.

Control Plane Console은 Prometheus나 Grafana가 없는 target에서도 "지금 서비스가 요청을
제대로 처리하는가"를 보여줘야 한다. 이 모듈은 Gateway 프로세스 안에서 최근 window의
요청 결과와 지연 표본만 들고 있다가 요약을 만든다. 장기 추세와 여러 인스턴스 합산은
Prometheus가 소유한다.

백분위 계산 방법과 최소 표본 수는 성능 계약(configs/performance/slo.yaml의 statistics)이
소유한다. 같은 원시 표본으로 도구마다 다른 백분위가 나오지 않게 여기서도 그 규칙을 쓴다.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .configuration import load_yaml_mapping
from .project_paths import resolve_project_root

DEFAULT_WINDOW_SECONDS = 300.0
# 요청이 몰려도 메모리가 늘지 않도록 표본 수를 제한한다. 한도를 넘으면 오래된 표본부터 버린다.
MAX_SAMPLES_PER_SERIES = 20_000
_PERCENTILES = (("p50", 0.50), ("p95", 0.95))


def slo_minimum_samples(root: Path | None = None) -> dict[str, int]:
    """성능 계약이 선언한 백분위별 최소 표본 수를 읽는다."""
    config_root = root or resolve_project_root(required_paths=("configs/performance/slo.yaml",))
    statistics = load_yaml_mapping(config_root / "configs/performance/slo.yaml").get("statistics") or {}
    if statistics.get("percentile_method") != "nearest_rank":
        raise RuntimeError("recent traffic summary supports only the nearest_rank percentile method")
    minimum = statistics.get("minimum_samples") or {}
    return {name: int(minimum[name]) for name, _ in _PERCENTILES}


def nearest_rank(sorted_values: list[float], quantile: float) -> float:
    """정렬된 값에서 ceil(p x n)번째 값을 보간 없이 반환한다."""
    rank = max(1, math.ceil(quantile * len(sorted_values)))
    return sorted_values[rank - 1]


class RecentTrafficWindow:
    """최근 window 동안의 공개 API 요청 결과와 지연 표본."""

    def __init__(
        self,
        *,
        minimum_samples: Mapping[str, int],
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_samples: int = MAX_SAMPLES_PER_SERIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = window_seconds
        self._minimum_samples = dict(minimum_samples)
        self._clock = clock
        self._started = clock()
        self._requests: deque[tuple[float, int]] = deque(maxlen=max_samples)
        self._latency: deque[tuple[float, float]] = deque(maxlen=max_samples)
        self._first_chunk: deque[tuple[float, float]] = deque(maxlen=max_samples)

    def record_request(self, status_code: int) -> None:
        self._requests.append((self._clock(), status_code))

    def record_completion_latency(self, seconds: float) -> None:
        self._latency.append((self._clock(), seconds))

    def record_time_to_first_chunk(self, seconds: float) -> None:
        self._first_chunk.append((self._clock(), seconds))

    def _prune(self, now: float) -> None:
        horizon = now - self.window_seconds
        for series in (self._requests, self._latency, self._first_chunk):
            while series and series[0][0] < horizon:
                series.popleft()

    def _distribution(self, samples: deque[tuple[float, float]]) -> dict[str, Any]:
        values = sorted(value for _, value in samples)
        summary: dict[str, Any] = {"samples": len(values)}
        for name, quantile in _PERCENTILES:
            # 최소 표본에 못 미치면 숫자를 내지 않는다. 표본 수가 판정을 좌우하지 않게 한다.
            enough = len(values) >= self._minimum_samples[name]
            summary[name] = round(nearest_rank(values, quantile), 4) if enough and values else None
        return summary

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        self._prune(now)
        statuses = [status for _, status in self._requests]
        return {
            "window_seconds": self.window_seconds,
            "observed_seconds": round(min(self.window_seconds, now - self._started), 1),
            "percentile_method": "nearest_rank",
            "minimum_samples": dict(self._minimum_samples),
            "requests": {
                "total": len(statuses),
                "client_errors": sum(1 for status in statuses if 400 <= status < 500),
                "server_errors": sum(1 for status in statuses if status >= 500),
            },
            "completion_latency_seconds": self._distribution(self._latency),
            "time_to_first_chunk_seconds": self._distribution(self._first_chunk),
        }
