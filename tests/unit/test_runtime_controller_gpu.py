"""Runtime Controller의 GPU 예약·Admission·Plan/Apply 계약 회귀 테스트.

서비스 준비 상태와 GPU 예약을 혼동하지 않고, 검토한 계획 이외의
Docker 변경을 일으키지 않아야 한다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from tests.support.runtime_controller import load_runtime_controller as _load_runtime_controller


@pytest.mark.parametrize(("docker_state", "reserved"), [
    ("running", True), ("paused", True), ("restarting", True),
    ("created", False), ("exited", False), ("not_found", False),
])
def test_gpu_budget_uses_docker_reservation_not_serving_readiness(
    tmp_path, monkeypatch, docker_state, reserved
):
    # GPU 예산은 컨테이너가 요청을 처리할 수 있는지와 무관하게 예약을 보존한다.
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {"embedding-vllm": 0.20})

    class ObservedExecutor:
        async def status(self, service):
            return docker_state if service == "embedding-vllm" else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    participants = asyncio.run(controller._build_participants())
    secondary = next(p for p in participants if p.key == "embedding-vllm")
    assert secondary.active is reserved
    # 자동 퇴거에는 실제로 Running인 Runtime만 포함한다.
    assert secondary.evictable is (docker_state == "running")

    # 같은 상태는 운영 조회에도 실제 예약량으로 나타나야 한다.
    response = asyncio.run(controller.gpu_budget())
    import json
    ledger = json.loads(response.body)
    assert ledger["used"] == (0.20 if reserved else 0.0)


@pytest.mark.parametrize("docker_state", ["paused", "restarting"])
def test_reserved_but_not_running_runtime_cannot_be_activated_as_noop(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.20})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return docker_state if key == service else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    # Docker paused 상태의 Stop은 실패할 수 있다. 실행 불가능한 Stop Plan이나
    # 활성화 No-op을 발행하지 않고 운영자에게 Docker 상태 복구를 요구한다.
    for desired_state in ("active", "stopped"):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(controller._runtime_transition_plan(service, desired_state, force=False))
        assert raised.value.status_code == 409
        assert docker_state in str(raised.value.detail)


@pytest.mark.parametrize("docker_state", ["dead", "removing", "unknown"])
def test_unconfirmed_docker_state_denies_gpu_plan_and_budget(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.20})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return docker_state if key == service else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    with pytest.raises(HTTPException) as budget:
        asyncio.run(controller.gpu_budget())
    assert budget.value.status_code == 503
    with pytest.raises(HTTPException) as plan:
        asyncio.run(controller._runtime_transition_plan(service, "active", force=True))
    assert plan.value.status_code == 503


def test_paused_main_runtime_keeps_its_protected_gpu_reservation(tmp_path, monkeypatch):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.60})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class ObservedExecutor:
        async def status(self, key):
            return "paused" if key == controller._MAIN_SERVICE else "exited"

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    participants = asyncio.run(controller._build_participants())
    main = next(p for p in participants if p.key == controller._MAIN_SERVICE)
    assert main.active is True
    assert main.evictable is False
    # 예약되어 있고 퇴거할 수 없는 main을 무시하고 secondary를 시작하지 않는다.
    plan = asyncio.run(controller._runtime_transition_plan(service, "active", force=True))
    assert plan["admissible"] is False


@pytest.mark.parametrize("docker_state", ["running", "paused", "restarting"])
def test_non_running_gpu_reservation_cannot_be_automatically_evicted(
    tmp_path, monkeypatch, docker_state
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    victim, target = sorted(controller.CONTROLLABLE)[:2]
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {victim: 0.25, target: 0.85})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {target: []})
    mutations: list[str] = []

    class ObservedExecutor:
        async def status(self, service):
            return docker_state if service == victim else "exited"

        async def stop(self, service):
            mutations.append(service)
            raise AssertionError("unapproved Docker mutation")

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    plan = asyncio.run(controller._runtime_transition_plan(target, "active", force=True))
    if docker_state == "running":
        assert plan["admissible"] is True
        assert plan["stop"] == [victim]
    else:
        assert plan["admissible"] is False
        assert plan["stop"] == []
        with pytest.raises(HTTPException) as rejected:
            asyncio.run(controller.start_container(
                target, force=True, plan_digest=plan["plan_digest"], authorization=None
            ))
        assert rejected.value.status_code == 409
        assert mutations == []


def test_runtime_start_preserves_running_target_reservation_when_starting_prerequisite(
    tmp_path, monkeypatch
):
    # 기존 target이 실행 중이어도 누락된 선행 서비스의 예약 비용이 추가된다.
    # Plan과 Apply가 동일한 victim을 선택해야 GPU 상한을 넘지 않는다.
    import json

    controller = _load_runtime_controller(tmp_path, monkeypatch)
    target, prereq, victim = sorted(controller.CONTROLLABLE)[:3]
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {
        target: 0.60, prereq: 0.20, victim: 0.20,
    })
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {target: [prereq]})
    monkeypatch.setattr(controller, "_HEALTH_URL", {prereq: "http://test/health", target: "http://test/health"})
    states = {target: "running", prereq: "exited", victim: "running"}
    stopped: list[str] = []
    started: list[str] = []

    class ObservedExecutor:
        async def status(self, service):
            return states.get(service, "exited")

        async def stop(self, service):
            stopped.append(service)
            states[service] = "exited"
            return True

        async def start(self, service):
            started.append(service)
            states[service] = "running"
            return True

    async def healthy(*_args, **_kwargs):
        return True

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    monkeypatch.setattr(controller, "_wait_healthy", healthy)
    plan = asyncio.run(controller._runtime_transition_plan(target, "active", force=True))
    assert plan["admissible"] is True
    assert plan["stop"] == [victim]
    result = asyncio.run(controller.start_container(
        target, force=True, plan_digest=plan["plan_digest"], authorization=None
    ))
    assert json.loads(result.body)["evicted"] == [victim]
    assert stopped == [victim]
    assert started == [prereq]
    assert states[target] == "running"


def test_runtime_start_does_not_evict_active_prerequisite_even_if_lower_priority(
    tmp_path, monkeypatch
):
    # 적용 시 Admission을 다시 계산하더라도 선행 서비스는 Plan과 같이 보호해야 한다.
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    target, prereq, victim = sorted(controller.CONTROLLABLE)[:3]
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {
        target: 0.70, prereq: 0.20, victim: 0.20,
    })
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {target: [prereq]})
    monkeypatch.setattr(controller, "_CRITICALITY", {
        prereq: "retrieval_support_path",
        victim: "risk_signal_path",
    })
    states = {target: "exited", prereq: "running", victim: "running"}
    stopped: list[str] = []

    class ObservedExecutor:
        async def status(self, service):
            return states.get(service, "exited")

        async def stop(self, service):
            stopped.append(service)
            states[service] = "exited"
            return True

        async def start(self, service):
            states[service] = "running"
            return True

    async def healthy(*_args, **_kwargs):
        return True

    monkeypatch.setattr(controller, "_executor", lambda: ObservedExecutor())
    monkeypatch.setattr(controller, "_wait_healthy", healthy)
    plan = asyncio.run(controller._runtime_transition_plan(target, "active", force=True))
    assert plan["admissible"] is True
    assert plan["stop"] == [victim]
    asyncio.run(controller.start_container(
        target, force=True, plan_digest=plan["plan_digest"], authorization=None
    ))
    assert stopped == [victim]
    assert states[prereq] == "running"


def test_runtime_apply_rejects_different_victim_after_plan_review(
    tmp_path, monkeypatch
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    target, victim, other = sorted(controller.CONTROLLABLE)[:3]
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {
        target: 0.80, victim: 0.20, other: 0.20,
    })
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {target: []})
    states = {target: "exited", victim: "running", other: "exited"}
    mutations: list[str] = []

    class ObservedExecutor:
        status_calls = 0

        async def status(self, service):
            if service == other:
                self.status_calls += 1
                # Plan 유효성 검사 직후 외부 Docker 변경이 관측되는 상황.
                if self.status_calls >= 3:
                    return "running"
            return states.get(service, "exited")

        async def stop(self, service):
            mutations.append(service)
            return True

    executor = ObservedExecutor()
    monkeypatch.setattr(controller, "_executor", lambda: executor)
    # 초기 계획에서 victim만 중지할 수 있다. 재관측 결과가 달라지면 Apply는 거부한다.
    first_plan = asyncio.run(controller._runtime_transition_plan(target, "active", force=True))
    assert first_plan["stop"] == [victim]
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(controller.start_container(
            target, force=True, plan_digest=first_plan["plan_digest"], authorization=None
        ))
    assert rejected.value.status_code == 409
    assert mutations == []



@pytest.mark.parametrize("failed_service", ["secondary", "main"])
def test_docker_observation_error_denies_admission_without_releasing_gpu(
    tmp_path, monkeypatch, failed_service
):
    controller = _load_runtime_controller(tmp_path, monkeypatch)
    service = next(iter(controller.CONTROLLABLE))
    monkeypatch.setattr(controller, "_VRAM_FRACTION", {service: 0.20})
    monkeypatch.setattr(controller, "_START_PREREQUISITES", {service: []})

    class UnavailableExecutor:
        async def status(self, key):
            if (failed_service == "secondary" and key == service) or (
                failed_service == "main" and key == controller._MAIN_SERVICE
            ):
                raise RuntimeError("Docker daemon temporarily unavailable")
            return "exited"

    monkeypatch.setattr(controller, "_executor", lambda: UnavailableExecutor())
    with pytest.raises(HTTPException) as budget:
        asyncio.run(controller.gpu_budget())
    assert budget.value.status_code == 503
    assert "cannot observe GPU reservation" in str(budget.value.detail)

    with pytest.raises(HTTPException) as plan:
        asyncio.run(controller._runtime_transition_plan(service, "active", force=True))
    assert plan.value.status_code == 503
