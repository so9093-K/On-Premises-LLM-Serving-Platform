"""Per-GPU VRAM admission policy, shared by all serving controllers.

Each call is scoped to *one physical GPU reservation domain*. The current
managed Docker deployment uses the controller-local scope; placement across
multiple hosts/devices is calculated by resource_placement, using this *same*
eviction/admission authority for every GPU. Fractions cannot be summed across
different devices or hosts. Fractions are static policy reservations, not
measured free bytes or proof that model weights will fit.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .resource_identity import CONTROLLER_LOCAL_GPU, GpuResourceId

DEFAULT_CEILING = 0.95
# fraction에 대한 float 연산(예: 0.85 - 0.785)이 오차로 인해 불필요한 victim을
# 추가로 요구하거나 정확히 맞는 경우를 거부하지 않도록 두는 허용 오차.
_EPS = 1e-9


@dataclass(frozen=True)
class Participant:
    key: str
    vram_fraction: float
    active: bool
    # priority가 높을수록 나중에 축출된다. main 모델이 가장 높으며 다른 모델을 위한
    # 공간 확보를 위해 자동 축출되지 않는다(evictable=False).
    priority: int = 0
    evictable: bool = True
    # 서술적 역할(resource_control.criticality). budget view에 노출되어 운영자가
    # 축출 후보가 무엇을 저하시킬지 알 수 있게 한다. planner 자체는(priority/fraction
    # 순으로 정렬하므로) 이 값을 사용하지 않는다.
    criticality: str | None = None
    resource_pool: GpuResourceId = CONTROLLER_LOCAL_GPU


@dataclass(frozen=True)
class AdmissionResult:
    feasible: bool
    victims: tuple[str, ...] = ()
    required: float = 0.0
    used_by_others: float = 0.0
    ceiling: float = DEFAULT_CEILING
    reason: str = ""

    @property
    def already_fits(self) -> bool:
        return self.feasible and not self.victims

    @property
    def available(self) -> float:
        return self.ceiling - self.used_by_others


def _validate_pool(participants: list[Participant], ceiling: float) -> None:
    if isinstance(ceiling, bool) or not math.isfinite(ceiling) or not 0.0 < ceiling <= 1.0:
        raise ValueError("GPU budget ceiling must be finite and in (0, 1]")
    pools: set[GpuResourceId] = set()
    keys: set[str] = set()
    for participant in participants:
        if not isinstance(participant.resource_pool, GpuResourceId):
            raise ValueError("GPU participant requires a valid resource pool")
        if not isinstance(participant.key, str) or not participant.key:
            raise ValueError("GPU participant requires a runtime key")
        if participant.key in keys:
            raise ValueError(f"duplicate GPU participant: {participant.key}")
        keys.add(participant.key)
        pools.add(participant.resource_pool)
        if isinstance(participant.vram_fraction, bool) or not math.isfinite(participant.vram_fraction) or not 0 < participant.vram_fraction <= 1:
            raise ValueError(f"invalid GPU fraction for participant: {participant.key}")
    if len(pools) > 1:
        raise ValueError("cannot combine reservations from different GPU resource pools")


def plan_activation(
    participants: list[Participant],
    target_key: str,
    target_fraction: float,
    *,
    ceiling: float = DEFAULT_CEILING,
) -> AdmissionResult:
    """``target_key``가 ``target_fraction``만큼의 GPU를 사용해도 되는지 판단한다.

    The target's own current residency does not count against it (so reloading or
    replacing an already-active runtime is feasible in place). If it does not fit,
    evictable active participants are selected lowest-priority-first (largest
    fraction first within a priority, to minimise the number stopped) until enough
    room is freed. If even stopping every evictable participant is insufficient,
    the result is infeasible with no victims.
    """
    _validate_pool(participants, ceiling)
    if not isinstance(target_key, str) or not target_key:
        raise ValueError("target key is required")
    if isinstance(target_fraction, bool) or not math.isfinite(target_fraction) or not 0 < target_fraction <= 1:
        raise ValueError("target GPU fraction must be finite and in (0, 1]")
    others = [p for p in participants if p.key != target_key]
    used_by_others = sum(p.vram_fraction for p in others if p.active)
    available = ceiling - used_by_others

    if target_fraction <= available + _EPS:
        return AdmissionResult(
            feasible=True,
            victims=(),
            required=target_fraction,
            used_by_others=used_by_others,
            ceiling=ceiling,
        )

    deficit = target_fraction - available
    candidates = sorted(
        (p for p in others if p.active and p.evictable),
        key=lambda p: (p.priority, -p.vram_fraction, p.key),
    )
    victims: list[str] = []
    freed = 0.0
    for candidate in candidates:
        if freed >= deficit - _EPS:
            break
        victims.append(candidate.key)
        freed += candidate.vram_fraction

    if freed < deficit - _EPS:
        return AdmissionResult(
            feasible=False,
            victims=(),
            required=target_fraction,
            used_by_others=used_by_others,
            ceiling=ceiling,
            reason=(
                f"{target_key} needs {target_fraction:.3f} but only "
                f"{available + freed:.3f} can be freed under ceiling {ceiling:.3f}"
            ),
        )

    return AdmissionResult(
        feasible=True,
        victims=tuple(victims),
        required=target_fraction,
        used_by_others=used_by_others,
        ceiling=ceiling,
    )


def budget_snapshot(
    participants: list[Participant], *, ceiling: float = DEFAULT_CEILING
) -> dict:
    """참여자별 비용·상태와 전체 예산을 포함한 운영자용 ledger를 반환한다."""
    _validate_pool(participants, ceiling)
    used = sum(p.vram_fraction for p in participants if p.active)
    return {
        "ceiling": ceiling,
        "used": round(used, 4),
        "free": round(ceiling - used, 4),
        "participants": [
            {
                "key": p.key,
                "vram_fraction": p.vram_fraction,
                "active": p.active,
                "priority": p.priority,
                "evictable": p.evictable,
                "criticality": p.criticality,
            }
            for p in participants
        ],
    }
