"""메인 모델 전환 전 정책·GPU 예약 예산을 읽기 전용으로 투영한다.

실제 전환 요청은 Runtime Controller에서 같은 Admission을 다시 검사하며,
여기서 통과했다는 사실은 모델 가중치가 실제 적재된다는 보장이 아니다.
"""

from __future__ import annotations

from ..gpu_budget import Participant, plan_activation


def project_switch_preflight(
    *,
    active: bool,
    policy_error_code: str | None,
    participants: list[Participant] | None,
    target_key: str,
    target_fraction: float,
    ceiling: float,
) -> dict:
    """관측 실패는 빈 GPU로 추측하지 않고 판단 불가로 표시한다."""
    base: dict = {
        "status": "unknown",
        "reason_code": "GPU_BUDGET_OBSERVATION_FAILED",
        "required_fraction": None,
        "available_fraction": None,
        "ceiling_fraction": None,
        "stop": [],
    }
    if active:
        return {**base, "status": "current", "reason_code": None}
    if policy_error_code is not None:
        return {**base, "status": "blocked", "reason_code": policy_error_code}
    if participants is None:
        return base

    result = plan_activation(
        participants,
        target_key,
        target_fraction,
        ceiling=ceiling,
    )
    fields = {
        "required_fraction": round(result.required, 4),
        "available_fraction": round(result.available, 4),
        "ceiling_fraction": round(result.ceiling, 4),
    }
    if result.already_fits:
        return {**base, **fields, "status": "fits", "reason_code": None}
    if result.feasible:
        return {
            **base, **fields, "status": "needs_stop",
            "reason_code": "GPU_BUDGET_REQUIRES_STOP",
            "stop": list(result.victims),
        }
    return {
        **base, **fields, "status": "infeasible",
        "reason_code": "GPU_BUDGET_EXCEEDED",
    }
