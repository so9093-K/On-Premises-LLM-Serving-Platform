"""Runtime 전환의 관측·수렴 판정. HTTP 라우터와 독립적으로 테스트할 수 있다."""

from __future__ import annotations

from typing import Any

from .services.runtime_controller_client import (
    RuntimeControllerClient,
    RuntimeControllerRequestError,
    RuntimeControllerUnavailableError,
)


def _secondary_converged(desired_state: str, observed_state: str | None) -> bool:
    if desired_state == "active":
        return observed_state == "running"
    return observed_state in {"exited", "not_found"}


async def _best_effort_secondary_before(
    runtime_controller: RuntimeControllerClient | None,
    container: str,
    desired_state: str,
) -> dict[str, Any]:
    observed_state: str | None = None
    if runtime_controller is not None:
        try:
            observed_state = (await runtime_controller.get_status()).get(container, "not_found")
        except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
            observed_state = None
    return {"desired_state": desired_state, "observed_state": observed_state}


async def _verify_secondary_transition(
    runtime_controller: RuntimeControllerClient,
    *,
    container: str,
    desired_state: str,
    started: list[str],
    stopped: list[str],
    evicted: list[str],
) -> dict[str, Any]:
    statuses = await runtime_controller.get_status()
    observed_state = statuses.get(container, "not_found")
    effects: dict[str, str] = {}
    for name in sorted(set([*started, *stopped, *evicted])):
        effects[name] = statuses.get(name, "not_found")
    effects_converged = all(statuses.get(name, "not_found") == "running" for name in started)
    effects_converged = effects_converged and all(
        statuses.get(name, "not_found") in {"exited", "not_found"}
        for name in [*stopped, *evicted]
    )
    return {
        "converged": _secondary_converged(desired_state, observed_state) and effects_converged,
        "source": "runtime_controller_container_status",
        "desired_state": desired_state,
        "observed_state": observed_state,
        "effects": effects,
    }


async def _best_effort_main_before(runtime_controller: RuntimeControllerClient) -> dict[str, Any]:
    try:
        snapshot = await runtime_controller.main_model()
    except (RuntimeControllerRequestError, RuntimeControllerUnavailableError):
        return {"runtime_state": None, "observed_state": None}
    observed = snapshot.get("observed_runtime") or {}
    return {
        "runtime_state": snapshot.get("runtime_state"),
        "observed_state": observed.get("status"),
        "container_state": observed.get("container_state"),
    }


async def _verify_main_transition(
    runtime_controller: RuntimeControllerClient,
    *,
    desired_state: str,
    evicted: list[str],
) -> dict[str, Any]:
    snapshot = await runtime_controller.main_model()
    observed = snapshot.get("observed_runtime") or {}
    observed_status = observed.get("status")
    container_state = observed.get("container_state")
    runtime_state = snapshot.get("runtime_state")
    if desired_state == "active":
        target_converged = (
            runtime_state == "active"
            and observed_status == "ready"
            and container_state == "running"
        )
    else:
        # 컨테이너 자체가 없는 경우 Backend는 status=unavailable,
        # container_state=not_found로 보고한다. 중지 요청에 대해서는
        # 없는 컨테이너도 예약이 없는 수렴 상태다.
        target_converged = (
            runtime_state == "stopped"
            and container_state != "running"
            and (observed_status == "stopped" or container_state == "not_found")
        )
    effects: dict[str, str] = {}
    effects_converged = True
    if evicted:
        statuses = await runtime_controller.get_status()
        for name in sorted(set(evicted)):
            effects[name] = statuses.get(name, "not_found")
        effects_converged = all(state in {"exited", "not_found"} for state in effects.values())
    return {
        "converged": target_converged and effects_converged,
        "source": "main_model_observed",
        "desired_state": desired_state,
        "runtime_state": runtime_state,
        "observed_state": observed_status,
        "container_state": container_state,
        "effects": effects,
    }


