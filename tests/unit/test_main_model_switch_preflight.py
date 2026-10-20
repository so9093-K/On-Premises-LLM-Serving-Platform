"""모델 전환 전 GPU 정책 판정은 읽기 전용이며 실패를 허용으로 오해하지 않는다."""

from __future__ import annotations

import asyncio
import json

from ai_model_serving.gpu_budget import Participant
from ai_model_serving.main_model.switch_preflight import project_switch_preflight
from tests.support.runtime_controller import load_runtime_controller


def _preflight(*, fraction: float, participants: list[Participant] | None, blocked: str | None = None, active: bool = False):
    return project_switch_preflight(
        active=active,
        policy_error_code=blocked,
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


def test_profiles_endpoint_reports_gpu_observation_failure_without_allowing_switch(
    tmp_path, monkeypatch,
):
    controller = load_runtime_controller(tmp_path, monkeypatch)

    class UnavailableExecutor:
        async def status(self, _service):
            raise RuntimeError("Docker unavailable")

    monkeypatch.setattr(controller, "_executor", lambda: UnavailableExecutor())
    result = asyncio.run(controller.main_model_profiles())
    profiles = json.loads(result.body)["profiles"]
    assert profiles
    for profile in profiles:
        if not profile["active"] and profile["compatibility"]["status"] != "incompatible":
            assert profile["switch_preflight"]["status"] == "unknown"
            assert profile["switch_preflight"]["available_fraction"] is None
