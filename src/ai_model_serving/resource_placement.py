"""명시적으로 제공된 GPU 자원 목록을 사용해 결정론적으로 배치 계획을 수립한다.

Candidate의 하드웨어·모델 적합성은 호출자가 이미 확인한 것으로 간주한다.
GPU 이름이나 예약 비율만으로 모델이 실제 GPU에 적합한지 추정하지 않는다.
하나의 실행 후보가 여러 GPU를 예약할 수 있으며, 단일 GPU도 동일한 계약을 따른다.

Plan은 읽기 전용이다. 실제 적용 권한은 Revision/Digest 검증부터 자원 예약까지
원자적으로 처리해야 한다. Digest만으로 분산 Lock이나 호스트 간 Fencing을
대체할 수 없다.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from .gpu_budget import Participant, plan_activation
from .resource_identity import GpuResourceId


@dataclass(frozen=True)
class GpuPool:
    resource: GpuResourceId
    ceiling: float
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource, GpuResourceId):
            raise ValueError("GPU pool must have an explicit host/device identity")
        if isinstance(self.ceiling, bool) or not math.isfinite(self.ceiling) or not 0 < self.ceiling <= 1:
            raise ValueError("GPU pool ceiling must be finite and in (0, 1]")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("GPU pool generation must be a non-negative integer")


@dataclass(frozen=True)
class GpuDemand:
    resource: GpuResourceId
    vram_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.resource, GpuResourceId):
            raise ValueError("GPU demand requires a resource identity")
        if isinstance(self.vram_fraction, bool) or not math.isfinite(self.vram_fraction) or not 0 < self.vram_fraction <= 1:
            raise ValueError("GPU demand must be finite and in (0, 1]")


@dataclass(frozen=True)
class PlacementCandidate:
    """장치별 예약량이 해석된, 명시적으로 적합 판정을 받은 GPU 집합."""

    name: str
    demands: tuple[GpuDemand, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("placement candidate requires a name")
        if not self.demands:
            raise ValueError("placement candidate requires at least one GPU demand")
        pools = [d.resource for d in self.demands]
        if len(set(pools)) != len(pools):
            raise ValueError("placement candidate cannot reserve the same GPU twice")


@dataclass(frozen=True)
class PlacementDecision:
    runtime_key: str
    candidate: str | None
    resource_ids: tuple[GpuResourceId, ...]
    victims: tuple[str, ...]
    feasible: bool
    requires_force: bool
    admissible: bool
    plan_digest: str
    reason: str | None = None


def plan_placement(
    pools: list[GpuPool],
    participants: list[Participant],
    target_key: str,
    candidates: list[PlacementCandidate],
    *,
    force: bool = False,
) -> PlacementDecision:
    """서로 다른 GPU의 예약 예산을 섞지 않고 검증된 실행 후보를 선택한다.

    허용·퇴거 우선순위는 `gpu_budget.plan_activation`만이 결정한다.
    실행 중인 Runtime을 다른 GPU 집합으로 조용히 옮기지 않으며,
    복수 GPU Runtime을 퇴거할 때는 일부 Shard가 아닌 전체를 중지한다.
    동일 조건에서는 Candidate 선언 순서로 결정한다.
    """
    if not isinstance(target_key, str) or not target_key:
        raise ValueError("target runtime key is required")
    if not isinstance(force, bool):
        raise ValueError("force must be boolean")
    by_resource = {pool.resource: pool for pool in pools}
    if len(by_resource) != len(pools):
        raise ValueError("duplicate GPU pool identity")
    names = [candidate.name for candidate in candidates]
    if len(names) != len(set(names)):
        raise ValueError("duplicate placement candidate name")
    observed: set[tuple[GpuResourceId, str]] = set()
    eviction_policy: dict[str, tuple[int, bool]] = {}
    for participant in participants:
        if participant.resource_pool not in by_resource:
            raise ValueError(f"unknown GPU pool for runtime: {participant.key}")
        key = (participant.resource_pool, participant.key)
        if key in observed:
            raise ValueError(f"duplicate runtime reservation in GPU pool: {participant.key}")
        observed.add(key)
        if isinstance(participant.vram_fraction, bool) or not math.isfinite(participant.vram_fraction) or not 0 < participant.vram_fraction <= 1:
            raise ValueError(f"invalid GPU reservation: {participant.key}")
        # Victim은 모든 GPU에서 중지되므로 퇴거 정책도 Runtime 전체에서 같아야 한다.
        # 한 Shard의 허용으로 다른 Shard의 보호 정책을 우회하지 않는다.
        policy = (participant.priority, participant.evictable)
        if eviction_policy.setdefault(participant.key, policy) != policy:
            raise ValueError(f"inconsistent runtime eviction policy: {participant.key}")
    for candidate in candidates:
        for demand in candidate.demands:
            if demand.resource not in by_resource:
                raise ValueError(f"candidate {candidate.name} references an unknown GPU pool")

    snapshot = {
        "runtime": target_key,
        "force": force,
        "pools": [(p.resource.host_id, p.resource.device_id, p.ceiling, p.generation)
                  for p in sorted(pools, key=lambda p: p.resource)],
        "participants": [
            (p.resource_pool.host_id, p.resource_pool.device_id, p.key,
             p.vram_fraction, p.active, p.priority, p.evictable, p.criticality)
            for p in sorted(participants, key=lambda p: (p.resource_pool, p.key))
        ],
        "candidates": [
            (c.name, [(d.resource.host_id, d.resource.device_id, d.vram_fraction)
                      for d in c.demands])
            for c in candidates
        ],
    }
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    active_scopes = {p.resource_pool for p in participants if p.key == target_key and p.active}
    options: list[tuple[int, int, PlacementCandidate, tuple[str, ...]]] = []

    def fits_after_stops(demands: tuple[GpuDemand, ...], stopped: set[str]) -> bool:
        # 복수 GPU Runtime을 중지하면 해당 Runtime의 모든 GPU 예약량이 반환된다.
        for demand in demands:
            pool = by_resource[demand.resource]
            used = sum(
                p.vram_fraction for p in participants
                if p.resource_pool == demand.resource and p.active
                and p.key != target_key and p.key not in stopped
            )
            if used + demand.vram_fraction > pool.ceiling + 1e-9:
                return False
        return True
    for index, candidate in enumerate(candidates):
        required_scopes = {d.resource for d in candidate.demands}
        if active_scopes and active_scopes != required_scopes:
            continue
        victims: set[str] = set()
        for demand in candidate.demands:
            pool = by_resource[demand.resource]
            local = [p for p in participants if p.resource_pool == pool.resource]
            admission = plan_activation(local, target_key, demand.vram_fraction, ceiling=pool.ceiling)
            if not admission.feasible:
                break
            victims.update(admission.victims)
        else:
            # GPU별 Admission 정책을 유지하면서 전체 GPU 관점의 중복 퇴거를 제거한다.
            # 퇴거가 불필요한 경우 우선순위가 높은 Runtime부터 유지한다.
            priority = {p.key: p.priority for p in participants if p.key in victims}
            for name in sorted(victims, key=lambda key: (-priority[key], key)):
                remaining = victims - {name}
                if fits_after_stops(candidate.demands, remaining):
                    victims = remaining
            options.append((len(victims), index, candidate, tuple(sorted(victims))))
    if not options:
        return PlacementDecision(target_key, None, (), (), False, False, False, digest,
                                 "no eligible GPU resource group can satisfy the reservation")
    _, _, selected, victims = min(options, key=lambda option: (option[0], option[1]))
    requires_force = bool(victims) and not force
    return PlacementDecision(
        target_key, selected.name,
        tuple(d.resource for d in selected.demands),
        victims, True, requires_force, not requires_force, digest,
    )


def require_current_placement(
    reviewed: PlacementDecision,
    pools: list[GpuPool],
    participants: list[Participant],
    candidates: list[PlacementCandidate],
    *,
    force: bool = False,
) -> PlacementDecision:
    """예약 직전에 권위 있는 소유자의 Lock 안에서 Plan을 다시 계산한다.

    호출자는 상태 비교부터 자원 예약 완료까지 공유 Lock/CAS를 유지해야 한다.
    그렇지 않으면 안전한 원격 적용을 보장할 수 없다.
    """
    fresh = plan_placement(pools, participants, reviewed.runtime_key, candidates, force=force)
    if fresh.plan_digest != reviewed.plan_digest or fresh.candidate != reviewed.candidate:
        raise ValueError("RESOURCE_PLAN_CHANGED")
    if not fresh.admissible:
        raise ValueError("RESOURCE_PLAN_NOT_ADMISSIBLE")
    return fresh
