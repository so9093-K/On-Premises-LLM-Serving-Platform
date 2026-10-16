"""Deterministic GPU placement decisions over an explicit resource inventory.

A Candidate is already hardware/model-qualified by its caller: this module
never guesses whether a model fits a GPU from a device name or VRAM fraction.
One candidate may reserve multiple GPUs for an explicitly supplied execution
group. Single-host/single-GPU is the same contract with one pool and candidate.

Plans are read-only. The controlling authority must atomically revalidate the
revision/digest and reserve resources before executing; a digest alone is NOT a
distributed lock or a cross-host fencing token.
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
    """Explicitly eligible device group, with per-device resolved reservations."""

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
    """Choose from caller-approved GPU groups without mixing resource budgets.

    Admission and eviction priority come *only* from gpu_budget.plan_activation.
    A running runtime cannot silently migrate to a different set of GPUs:
    explicitly stop it first. Stopping a multi-GPU victim stops its entire
    runtime, not an individual shard. Candidate declaration order breaks ties.
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
    for participant in participants:
        if participant.resource_pool not in by_resource:
            raise ValueError(f"unknown GPU pool for runtime: {participant.key}")
        key = (participant.resource_pool, participant.key)
        if key in observed:
            raise ValueError(f"duplicate runtime reservation in GPU pool: {participant.key}")
        observed.add(key)
        if isinstance(participant.vram_fraction, bool) or not math.isfinite(participant.vram_fraction) or not 0 < participant.vram_fraction <= 1:
            raise ValueError(f"invalid GPU reservation: {participant.key}")
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
    """Recompute a plan under the owner's lock immediately before reservation.

    The caller must hold an authoritative, shared lock/CAS across compare and
    resource reservation. Without that, this check is not a safe remote apply.
    """
    fresh = plan_placement(pools, participants, reviewed.runtime_key, candidates, force=force)
    if fresh.plan_digest != reviewed.plan_digest or fresh.candidate != reviewed.candidate:
        raise ValueError("RESOURCE_PLAN_CHANGED")
    if not fresh.admissible:
        raise ValueError("RESOURCE_PLAN_NOT_ADMISSIBLE")
    return fresh
