"""모든 Serving Controller가 공유하는 개별 GPU별 VRAM 허용 정책.

한 번의 판단은 **하나의 물리 GPU 예약 범위**에 한정한다. 현재 Managed Docker
배포는 Controller 로컬 호환 범위를 사용한다. 서로 다른 GPU나 호스트의 배치는
`resource_placement`가 수행하되, GPU별 퇴거·허용 판단은 동일한 정책을 따른다.
다른 장치의 예약 비율은 합산하지 않는다. 이 비율은 정적 정책 예약이며
실측 유휴 VRAM 또는 모델 가중치가 적재될 수 있다는 증거가 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .resource_identity import CONTROLLER_LOCAL_GPU, GpuResourceId

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
    ceiling: float
    victims: tuple[str, ...] = ()
    required: float = 0.0
    used_by_others: float = 0.0
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
    ceiling: float,
) -> AdmissionResult:
    """``target_key``가 ``target_fraction``만큼의 GPU를 사용해도 되는지 판단한다.

    Target 자신이 이미 점유 중인 예약량은 다른 Runtime의 사용량에 포함하지 않아
    현재 Runtime을 같은 GPU에서 교체할 수 있게 한다. 여유가 부족하면 퇴거 가능한
    Runtime을 낮은 우선순위부터 선정한다. 우선순위가 같으면 큰 예약량부터
    선택하여 중지할 Runtime 수를 줄인다. 모든 퇴거 후보를 중지해도 부족하면
    Victim 없이 허용 불가능한 결과를 반환한다.
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
    participants: list[Participant], *, ceiling: float
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
