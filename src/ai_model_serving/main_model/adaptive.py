"""자동 선택은 기존 Main Model 전환 엔진을 통해서만 실행한다."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Awaitable, Callable

from ..host_resource_probe import HostResourceSnapshot
from .adaptive_backend import fitting_gpu
from .control import MainModelManager, MainModelSwitchError

_TERMINAL = {"completed", "failed", "rollback_failed"}
_logger = logging.getLogger(__name__)


class AdaptiveMainModelControl:
    def __init__(
        self,
        manager: MainModelManager,
        policy: dict,
        resources: Callable[[], Awaitable[HostResourceSnapshot]],
        *,
        gpu_error: str | None = None,
    ):
        self.manager = manager
        self.policy = policy
        self.resources = resources
        self.gpu_error = gpu_error
        self.mutation_lock = asyncio.Lock()
        for key in (
            "poll_interval_seconds",
            "recovery_samples",
            "failure_samples",
            "minimum_residency_seconds",
            "failure_cooldown_seconds",
            "gpu_minimum_total_mib",
            "gpu_start_margin_mib",
            "gpu_pressure_free_mib",
        ):
            if (
                type(policy.get(key)) not in (int, float)
                or not math.isfinite(policy[key])
                or policy[key] <= 0
            ):
                raise ValueError(f"invalid automatic runtime policy: {key}")
        for key in ("recovery_samples", "failure_samples"):
            if type(policy[key]) is not int:
                raise ValueError(f"invalid sample count: {key}")

    def _record(self, **fields) -> dict:
        def update(state):
            selection = state.setdefault(
                "runtime_selection",
                {
                    "mode": "automatic",
                    "reason_code": "STARTING_CPU",
                    "healthy_samples": 0,
                    "failure_samples": 0,
                },
            )
            selection.update(fields)

        return self.manager.state_store.update(update)

    async def step(self, *, now: float | None = None) -> None:
        async with self.mutation_lock:
            await self._step(now=now)

    async def _step(self, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        state = self.manager.state_store.read()
        selection = dict(state.get("runtime_selection") or {})
        operation = state.get("last_operation") or {}
        if operation and operation.get("status") not in _TERMINAL:
            return
        # 한 실패의 backoff는 한 번만 기록해 deadline이 계속 뒤로 밀리지 않게 한다.
        if operation.get("status") in {"failed", "rollback_failed"} and operation.get(
            "id"
        ) != selection.get("last_failed_operation"):
            retry_key = (
                "gpu_retry_at"
                if operation.get("requested_profile") == self.policy["gpu_profile"]
                else "cpu_retry_at"
            )
            self._record(
                last_failed_operation=operation["id"],
                **{retry_key: now + self.policy["failure_cooldown_seconds"]},
            )
            selection = dict(self.manager.state_store.read()["runtime_selection"])
        if state.get("runtime_state") == "stopped":
            self._record(reason_code="OPERATOR_STOPPED")
            return
        observed = await self.resources()
        self._record(observed_at=now, resources=asdict(observed))
        active_id = state.get("active_profile")
        if active_id != selection.get("active_profile"):
            self._record(
                active_profile=active_id,
                last_activation_at=now,
                healthy_samples=0,
                failure_samples=0,
            )
            selection = dict(self.manager.state_store.read()["runtime_selection"])
        profile = self.manager.catalog.profiles.get(active_id)
        if profile is None:
            await self._switch_cpu(now, selection, "CPU_BOOTSTRAP")
            return
        runtime: dict = {}
        try:
            runtime = await self.manager.backend.observe_runtime(self.manager.catalog)
            healthy = (
                runtime.get("status") == "ready"
                and runtime.get("profile_id") == active_id
            )
        except Exception:
            healthy = False
        cpu = profile.runtime_backend == "llama-cpp"
        if not cpu:
            # 실행 중인 GPU의 메모리는 자기 모델이 이미 사용한다. 시작 예약량과 비교하지 않는다.
            gpu_index = runtime.get("gpu_device_index")
            device = next((g for g in observed.gpus if g.index == gpu_index), None)
            safe = (
                healthy
                and device is not None
                and device.free_mib >= self.policy["gpu_pressure_free_mib"]
            )
            failures = 0 if safe else int(selection.get("failure_samples", 0)) + 1
            self._record(
                failure_samples=failures,
                healthy_samples=0,
                reason_code="GPU_SERVING" if safe else "GPU_HEALTH_OR_MEMORY_PRESSURE",
            )
            if failures >= self.policy["failure_samples"]:
                await self._switch_cpu(now, selection, "GPU_HEALTH_OR_MEMORY_PRESSURE")
            elif healthy:
                await self.manager.reconcile_if_restarted()
            return
        if not healthy or state.get("gate") != "open":
            await self._switch_cpu(now, selection, "CPU_RUNTIME_UNAVAILABLE")
            return
        await self.manager.reconcile_if_restarted()
        gpu = self.manager.catalog.profiles.get(self.policy["gpu_profile"])
        fits = gpu is not None and fitting_gpu(observed, gpu, self.policy) is not None
        streak = int(selection.get("healthy_samples", 0)) + 1 if fits else 0
        reason = self.gpu_error or (
            "GPU_RECOVERY_PENDING" if fits else "GPU_MEMORY_INSUFFICIENT"
        )
        if observed.gpu_observation_error:
            reason = "GPU_OBSERVATION_UNAVAILABLE"
        if now < selection.get("gpu_retry_at", 0):
            reason = "GPU_FAILURE_BACKOFF"
            streak = 0
        self._record(healthy_samples=streak, failure_samples=0, reason_code=reason)
        last_change = float(selection.get("last_activation_at", 0))
        if (
            fits
            and streak >= self.policy["recovery_samples"]
            and now - last_change >= self.policy["minimum_residency_seconds"]
        ):
            self._record(
                reason_code="GPU_RECOVERY_VALIDATION",
                healthy_samples=0,
                last_activation_at=now,
            )
            self.manager.request_switch(
                self.policy["gpu_profile"], confirm_unverified=True
            )

    async def _switch_cpu(self, now: float, selection: dict, reason: str) -> None:
        # 장애 상태를 기존 검증 결과로 계속 제공하지 않는다. 실제 교체는 Drain 뒤에만 한다.
        self.manager.state_store.update(lambda state: state.update(gate="closed"))
        self._record(reason_code=reason, healthy_samples=0, failure_samples=0)
        if now < selection.get("cpu_retry_at", 0):
            return
        self._record(last_activation_at=now)
        self.manager.request_switch(self.policy["cpu_profile"], confirm_unverified=True)

    async def run(self) -> None:
        try:
            await self.manager.initialize()
        except Exception as exc:
            # Core liveness와 모델의 재검증 실패는 독립적이다. 다음 tick이 CPU 복구를 시도한다.
            self.manager.record_initialization_failure(str(exc))
            _logger.exception(
                "Automatic runtime initialization failed; CPU recovery remains enabled"
            )
        while True:
            try:
                await self.step()
            except MainModelSwitchError:
                # 관리자 start/stop 또는 재시작 복구가 보유한 기존 전환 잠금을 존중한다.
                pass
            except Exception:
                _logger.exception("Automatic runtime observation failed")
                try:
                    self._record(reason_code="RUNTIME_OBSERVATION_UNAVAILABLE")
                except Exception:
                    _logger.exception("Automatic runtime state could not be recorded")
            await asyncio.sleep(self.policy["poll_interval_seconds"])
