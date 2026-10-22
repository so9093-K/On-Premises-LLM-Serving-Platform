"""자동 선택은 기존 Main Model 전환 엔진을 통해서만 실행한다."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Awaitable, Callable

from ..host_resource_probe import HostResourceSnapshot
from .adaptive_gpu import AdaptiveGpuPolicies
from .execution_policy import RECOVERING_POLICIES
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
        gpu_policies: AdaptiveGpuPolicies,
        admit_gpu: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.manager = manager
        self.policy = policy
        self.resources = resources
        self.gpu_policies = gpu_policies
        self.mutation_lock = asyncio.Lock()
        self.admit_gpu = admit_gpu
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
        mode = selection.get("mode", "automatic")
        if mode not in RECOVERING_POLICIES:
            return
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
            failure = {}
            if retry_key == "gpu_retry_at":
                error = operation.get("error")
                failure["gpu_condition"] = error if error in {
                    "GPU_DRIVER_INCOMPATIBLE", "GPU_DRIVER_COMPATIBILITY_UNKNOWN",
                } else "GPU_START_FAILED"
            self._record(
                last_failed_operation=operation["id"],
                **{retry_key: now + self.policy["failure_cooldown_seconds"]},
                **failure,
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
            if mode == "fallback":
                self._record(gpu_attempted=True)
            # 실행 중인 GPU의 메모리는 자기 모델이 이미 사용한다. 시작 예약량과 비교하지 않는다.
            gpu_uuid = runtime.get("gpu_device_uuid")
            device = next(
                (
                    g
                    for g in observed.gpus
                    if g.uuid == gpu_uuid and gpu_uuid is not None
                ),
                None,
            )
            condition = (
                "GPU_RUNTIME_UNHEALTHY"
                if not healthy
                else "GPU_OBSERVATION_UNAVAILABLE"
                if observed.gpu_observation_error or device is None
                else "GPU_MEMORY_PRESSURE"
                if device.free_mib < self.policy["gpu_pressure_free_mib"]
                else None
            )
            self._record(gpu_condition=condition)
            if condition is not None:
                # 압력·관측 실패 중에는 CPU 준비 실패나 재시도 유예가 Gate를 다시 열지 않는다.
                self.manager.state_store.update(
                    lambda state: state.update(gate="closed")
                )
                failures = int(selection.get("failure_samples", 0)) + 1
                reason = condition
                if (
                    operation.get("status") in {"failed", "rollback_failed"}
                    and operation.get("requested_profile") == self.policy["cpu_profile"]
                ):
                    reason = (
                        "CPU_FALLBACK_PREPARATION_FAILED"
                        if operation.get("stage") == "preparing"
                        else "CPU_FALLBACK_FAILED"
                    )
                self._record(
                    failure_samples=failures, healthy_samples=0, reason_code=reason
                )
                if failures >= self.policy["failure_samples"]:
                    await self._switch_cpu(now, selection, reason)
                return
            if state.get("gate") != "open":
                streak = int(selection.get("healthy_samples", 0)) + 1
                self._record(
                    healthy_samples=streak,
                    failure_samples=0,
                    reason_code="GPU_REVALIDATION_PENDING",
                )
                if streak < self.policy["recovery_samples"]:
                    return
            try:
                # CPU 재시도 유예와 독립적으로 같은 GPU 인스턴스를 Canary 재검증한다.
                await self.manager.reconcile_if_restarted()
            except Exception:
                self._record(healthy_samples=0, reason_code="GPU_REVALIDATION_FAILED")
                self._record(gpu_condition="GPU_REVALIDATION_FAILED")
                await self._switch_cpu(now, selection, "GPU_REVALIDATION_FAILED")
                return
            if self.manager.state_store.read().get("gate") == "open":
                self._record(
                    failure_samples=0, healthy_samples=0, reason_code="GPU_SERVING"
                )
            else:
                # 기존 재검증기는 Canary 실패를 내부에서 기록하고 유예할 수 있다.
                self._record(healthy_samples=0, reason_code="GPU_REVALIDATION_FAILED")
            return
        if not healthy or state.get("gate") != "open":
            await self._switch_cpu(now, selection, "CPU_RUNTIME_UNAVAILABLE")
            return
        await self.manager.reconcile_if_restarted()
        if mode == "fallback" and selection.get("gpu_attempted"):
            self._record(reason_code="CPU_FALLBACK_ACTIVE", healthy_samples=0)
            return
        candidate, blocked_reason = self.gpu_policies.choose(observed)
        fits = candidate is not None and blocked_reason is None
        candidate_view = (
            {
                **candidate.public_view(),
                "admissible": fits,
                "reason_code": blocked_reason,
            }
            if candidate
            else None
        )
        previous = selection.get("gpu_candidate") or {}
        same_candidate = candidate_view is not None and all(
            previous.get(key) == candidate_view.get(key)
            for key in ("uuid", "resource_variant")
        )
        streak = (
            (int(selection.get("healthy_samples", 0)) + 1 if same_candidate else 1)
            if fits
            else 0
        )
        self._record(gpu_candidate=candidate_view)
        if mode == "fallback" and not fits and blocked_reason not in {
            "GPU_OBSERVATION_UNAVAILABLE", "GPU_ARTIFACT_UNAVAILABLE",
        }:
            self._record(gpu_attempted=True, gpu_condition=blocked_reason)
        reason = "GPU_RECOVERY_PENDING" if fits else blocked_reason
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
            if self.admit_gpu is not None:
                try:
                    await self.admit_gpu(candidate.profile.vram_fraction)
                except Exception:
                    self._record(reason_code="GPU_BUDGET_BLOCKED", healthy_samples=0,
                                 **({"gpu_attempted": True, "gpu_condition": "GPU_BUDGET_BLOCKED"} if mode == "fallback" else {}))
                    return
            self._record(
                reason_code="GPU_RECOVERY_VALIDATION",
                healthy_samples=0,
                last_activation_at=now,
                **({"gpu_attempted": True} if mode == "fallback" else {}),
            )
            self.manager.catalog.profiles[candidate.profile.profile_id] = (
                candidate.profile
            )
            self._record(gpu_assignment=candidate.public_view())
            if hasattr(self.manager.backend, "bind_gpu"):
                self.manager.backend.bind_gpu(candidate)
            self.manager.request_switch(
                candidate.profile.profile_id, confirm_unverified=True
            )

    async def _switch_cpu(self, now: float, selection: dict, reason: str) -> None:
        # 장애 상태를 기존 검증 결과로 계속 제공하지 않는다. 실제 교체는 Drain 뒤에만 한다.
        self.manager.state_store.update(lambda state: state.update(gate="closed"))
        self._record(reason_code=reason, healthy_samples=0)
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
