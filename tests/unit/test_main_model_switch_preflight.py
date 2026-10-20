"""모델 전환 전 GPU 정책 판정은 읽기 전용이며 실패를 허용으로 오해하지 않는다."""

from __future__ import annotations

import asyncio
import httpx

from ai_model_serving.apps.runtime_controller import create_runtime_controller_app
from ai_model_serving.gpu_budget import Participant
from ai_model_serving.main_model.switch_preflight import project_switch_preflight


def _preflight(*, fraction: float, participants: list[Participant] | None, blocked: str | None = None, active: bool = False, switching: bool = False):
    return project_switch_preflight(
        active=active,
        policy_error_code=blocked,
        switch_in_progress=switching,
        participants=participants,
        target_key="main",
        target_fraction=fraction,
        ceiling=0.93,
    )


def test_preflight_reuses_reserved_gpu_budget_without_mutation():
    participants = [
        Participant("main", .65, True, evictable=False),
        Participant("embedding", .20, True, priority=1, evictable=True),
        Participant("risk", .10, True, evictable=False),
    ]
    fits = _preflight(fraction=.60, participants=participants)
    assert fits["status"] == "fits"
    assert fits["available_fraction"] == .63
    assert fits["stop"] == []

    needs_stop = _preflight(fraction=.68, participants=participants)
    assert needs_stop["status"] == "needs_stop"
    assert needs_stop["stop"] == ["embedding"]

    infeasible = _preflight(fraction=.92, participants=participants)
    assert infeasible["status"] == "infeasible"
    assert infeasible["stop"] == []
    assert infeasible["reason_code"] == "GPU_BUDGET_EXCEEDED"


def test_policy_block_and_observation_failure_never_return_fits():
    policy = _preflight(
        fraction=.76, participants=None, blocked="MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED",
    )
    assert policy["status"] == "blocked"
    assert policy["reason_code"] == "MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED"
    missing = _preflight(fraction=.76, participants=None)
    assert missing["status"] == "unknown"
    assert missing["available_fraction"] is None
    assert _preflight(fraction=.76, participants=None, active=True)["status"] == "current"
    switching = _preflight(fraction=.76, participants=[], switching=True)
    assert switching["status"] == "blocked"
    assert switching["reason_code"] == "MODEL_SWITCH_IN_PROGRESS"


def test_profiles_endpoint_blocks_candidates_during_running_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    app = create_runtime_controller_app()
    controller = app.state.controller
    monkeypatch.setattr(controller._main_model_manager, "switch_in_progress", lambda: True)

    class MustNotObserve:
        async def status(self, _service):
            raise AssertionError("진행 중인 전환 동안 Docker 예산을 새로 조회하면 안 된다")

    monkeypatch.setattr(controller, "_executor", lambda: MustNotObserve())

    async def fetch_profiles():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            return await client.get("/main-model/profiles")

    response = asyncio.run(fetch_profiles())
    assert response.status_code == 200
    profiles = response.json()["profiles"]
    for profile in profiles:
        if not profile["active"] and profile["compatibility"]["status"] != "incompatible":
            result = profile["switch_preflight"]
            assert result["status"] == "blocked"
            assert result["reason_code"] == "MODEL_SWITCH_IN_PROGRESS"


def test_profiles_endpoint_reports_gpu_observation_failure_without_allowing_switch(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    app = create_runtime_controller_app()
    controller = app.state.controller

    class UnavailableExecutor:
        async def status(self, _service):
            raise RuntimeError("Docker unavailable")

    monkeypatch.setattr(controller, "_executor", lambda: UnavailableExecutor())
    async def fetch_profiles():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return (await client.get("/main-model/profiles")).json()

    profiles = asyncio.run(fetch_profiles())["profiles"]
    assert profiles
    for profile in profiles:
        if not profile["active"] and profile["compatibility"]["status"] != "incompatible":
            assert profile["switch_preflight"]["status"] == "unknown"
            assert profile["switch_preflight"]["available_fraction"] is None


def test_slow_docker_observation_returns_unknown_within_controller_read_timeout(
    tmp_path, monkeypatch,
):
    # 내부 Controller 응답 제한(5초)을 넘기기 전에 실패한 GPU 관측을
    # 실행 가능으로 오인하지 않고 정상적인 unknown 응답으로 전달한다.
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    app = create_runtime_controller_app()
    controller = app.state.controller

    class SlowExecutor:
        async def status(self, _service):
            await asyncio.sleep(30)
            raise AssertionError("관측 지연은 사전 판단 제한 시간에 의해 취소돼야 한다")

    monkeypatch.setattr(controller, "_executor", lambda: SlowExecutor())

    async def fetch_profiles():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            return await client.get("/main-model/profiles")

    response = asyncio.run(asyncio.wait_for(fetch_profiles(), timeout=4.5))
    assert response.status_code == 200
    candidates = [p for p in response.json()["profiles"] if not p["active"]]
    assert candidates
    assert all(p["switch_preflight"]["status"] in {"unknown", "blocked"} for p in candidates)
    assert not any(p["switch_preflight"]["status"] == "fits" for p in candidates)
