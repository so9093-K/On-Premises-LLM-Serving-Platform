"""실제 장비 없이 단일·복수 호스트 및 GPU 배치 계약을 검증한다."""

from __future__ import annotations

import pytest

from ai_model_serving.gpu_budget import Participant, budget_snapshot, plan_activation
from ai_model_serving.resource_identity import CONTROLLER_LOCAL_GPU, GpuResourceId
from ai_model_serving.resource_placement import (
    GpuDemand,
    GpuPool,
    PlacementCandidate,
    plan_placement,
    require_current_placement,
)

H1_A = GpuResourceId("host-1", "GPU-a")
H1_B = GpuResourceId("host-1", "GPU-b")
H2_A = GpuResourceId("host-2", "GPU-a")


def pool(scope, *, generation=0, ceiling=0.93):
    return GpuPool(scope, ceiling, generation)


def runtime(name, scope, fraction, *, active=True, priority=50, evictable=True):
    return Participant(name, fraction, active, priority=priority, evictable=evictable,
                       resource_pool=scope)


def candidate(name, *requirements):
    return PlacementCandidate(name, tuple(GpuDemand(scope, fraction) for scope, fraction in requirements))


def test_single_pool_is_the_same_contract_as_one_host_fleet():
    participants = [runtime("main", H1_A, 0.70, evictable=False),
                    runtime("embed", H1_A, 0.10)]
    local = plan_activation(participants, "new", 0.2, ceiling=0.93)
    placement = plan_placement([pool(H1_A)], participants, "new",
                               [candidate("on-h1", (H1_A, 0.2))])
    assert local.victims == placement.victims == ("embed",)
    assert placement.requires_force and not placement.admissible
    assert plan_placement([pool(H1_A)], participants, "new",
                          [candidate("on-h1", (H1_A, 0.2))], force=True).admissible
    assert CONTROLLER_LOCAL_GPU not in placement.resource_ids


def test_two_devices_on_same_host_have_independent_capacity():
    participants = [runtime("main", H1_A, 0.87, evictable=False)]
    result = plan_placement([pool(H1_A), pool(H1_B)], participants, "new", [
        candidate("busy-device", (H1_A, 0.50)),
        candidate("idle-device", (H1_B, 0.50)),
    ])
    assert result.admissible
    assert result.candidate == "idle-device"
    assert result.resource_ids == (H1_B,)
    assert result.victims == ()


def test_same_device_names_on_different_hosts_never_share_a_budget():
    occupied = [runtime("main", H1_A, 0.91, evictable=False)]
    plan = plan_placement([pool(H1_A), pool(H2_A)], occupied, "embedding", [
        candidate("on-first", (H1_A, 0.20)),
        candidate("on-second", (H2_A, 0.20)),
    ])
    assert plan.admissible and plan.candidate == "on-second"
    assert plan.resource_ids == (H2_A,)


def test_multigpu_execution_group_reserves_all_selected_devices():
    pools = [pool(H1_A), pool(H1_B), pool(H2_A)]
    participants = [runtime("other", H1_A, 0.83, evictable=False),
                    runtime("other2", H2_A, 0.85, evictable=False)]
    requested = [candidate("tensor-parallel", (H1_A, 0.45), (H1_B, 0.45)),
                 candidate("two-host", (H1_B, 0.45), (H2_A, 0.45))]
    result = plan_placement(pools, participants, "main", requested)
    assert result.candidate is None
    assert not result.admissible
    participants = [runtime("other", H1_A, 0.35, evictable=False),
                    runtime("other2", H2_A, 0.85, evictable=False)]
    result = plan_placement(pools, participants, "main", requested)
    assert result.admissible and result.candidate == "tensor-parallel"
    assert result.resource_ids == (H1_A, H1_B)


def test_moving_an_active_runtime_requires_explicit_stop_and_new_reservation():
    participants = [runtime("main", H1_A, 0.50, evictable=False)]
    move = plan_placement([pool(H1_A), pool(H2_A)], participants, "main",
                          [candidate("on-second", (H2_A, 0.60))])
    assert not move.admissible and move.candidate is None


def test_multigpu_victim_is_never_selected_as_only_a_single_shard():
    participants = [runtime("distributed", H1_A, 0.3), runtime("distributed", H1_B, 0.3)]
    result = plan_placement([pool(H1_A), pool(H1_B)], participants, "new",
                            [candidate("a", (H1_A, 0.80))])
    assert result.victims == ("distributed",)
    assert result.requires_force


def test_multigpu_stop_releases_all_reservations_without_extra_victims():
    participants = [
        runtime("shared", H1_A, 0.50, priority=10),
        runtime("shared", H1_B, 0.50, priority=10),
        runtime("independent", H1_B, 0.40, priority=0),
    ]
    decision = plan_placement(
        [pool(H1_A, ceiling=0.95), pool(H1_B, ceiling=0.95)],
        participants, "new",
        [candidate("both", (H1_A, 0.60), (H1_B, 0.50))],
        force=True,
    )
    assert decision.admissible
    assert decision.victims == ("shared",)


def test_plan_digest_checks_changes_to_generation_placement_and_observed_reservations():
    pools = [pool(H1_A, generation=4)]
    candidates = [candidate("a", (H1_A, 0.2))]
    participants = [runtime("old", H1_A, 0.1)]
    reviewed = plan_placement(pools, participants, "new", candidates)
    assert require_current_placement(reviewed, pools, participants, candidates) == reviewed
    with pytest.raises(ValueError, match="RESOURCE_PLAN_CHANGED"):
        require_current_placement(reviewed, [pool(H1_A, generation=5)], participants, candidates)
    with pytest.raises(ValueError, match="RESOURCE_PLAN_CHANGED"):
        require_current_placement(reviewed, pools, [runtime("old", H1_A, 0.11)], candidates)
    with pytest.raises(ValueError, match="RESOURCE_PLAN_CHANGED"):
        require_current_placement(reviewed, pools, participants, [candidate("a", (H1_A, 0.21))])


@pytest.mark.parametrize("bad", [0.0, float("nan"), float("inf"), -0.1, 1.1, True])
def test_resource_budget_rejects_invalid_reservations_and_limits(bad):
    with pytest.raises(ValueError):
        plan_activation([], "new", bad)
    with pytest.raises(ValueError):
        GpuPool(H1_A, bad, 0)


def test_multi_pool_participants_fail_closed_in_legacy_single_gpu_planner():
    participants = [runtime("a", H1_A, 0.3), runtime("b", H2_A, 0.2)]
    with pytest.raises(ValueError, match="different GPU resource pools"):
        plan_activation(participants, "c", 0.2)
    with pytest.raises(ValueError, match="different GPU resource pools"):
        budget_snapshot(participants)


def test_invalid_inventory_identity_or_duplicate_reservation_is_rejected():
    with pytest.raises(ValueError, match="resource identifier"):
        GpuResourceId("", "GPU0")
    with pytest.raises(ValueError, match="duplicate GPU pool"):
        plan_placement([pool(H1_A), pool(H1_A)], [], "new", [candidate("a", (H1_A, 0.2))])
    with pytest.raises(ValueError, match="duplicate runtime reservation"):
        plan_placement([pool(H1_A)], [runtime("old", H1_A, 0.1),
                                      runtime("old", H1_A, 0.1)], "new",
                       [candidate("a", (H1_A, 0.2))])
    with pytest.raises(ValueError, match="unknown GPU pool"):
        plan_placement([pool(H1_A)], [], "new", [candidate("a", (H2_A, 0.2))])


def test_cannot_apply_preview_that_requires_force_as_if_it_were_approved():
    participants = [runtime("main", H1_A, 0.70, evictable=False), runtime("embed", H1_A, 0.15)]
    options = [candidate("a", (H1_A, 0.2))]
    reviewed = plan_placement([pool(H1_A)], participants, "new", options)
    assert reviewed.requires_force and not reviewed.admissible
    with pytest.raises(ValueError, match="RESOURCE_PLAN_NOT_ADMISSIBLE"):
        require_current_placement(reviewed, [pool(H1_A)], participants, options)

def test_gpu_demand_rejects_boolean_fraction():
    with pytest.raises(ValueError, match="GPU demand"):
        GpuDemand(H1_A, True)
    with pytest.raises(ValueError, match="invalid GPU reservation"):
        plan_placement([pool(H1_A)], [runtime("bad", H1_A, True)],
                       "new", [candidate("a", (H1_A, 0.2))])
