"""장치 식별·자원 정책 선택·실행 Admission을 분리한다."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from ..host_resource_probe import (
    GpuMemory,
    HostResourceSnapshot,
    gpu_from_mapping,
    valid_gpu_uuid,
)
from .catalog import MainModelProfile


def compute_capability(value: str | None) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return tuple(map(int, parts))


def device_fits(device: GpuMemory, profile: MainModelProfile, policy: dict) -> bool:
    required = math.ceil(device.total_mib * profile.vram_fraction) + int(
        policy["gpu_start_margin_mib"]
    )
    return (
        valid_gpu_uuid(device.uuid)
        and 0 < profile.vram_fraction <= policy["gpu_budget_ceiling"]
        and device.total_mib >= policy["gpu_minimum_total_mib"]
        and device.free_mib >= required
    )


@dataclass(frozen=True)
class GpuAssignment:
    device: GpuMemory
    profile: MainModelProfile
    policy_source: str

    def public_view(self) -> dict:
        return {
            "uuid": self.device.uuid,
            "name": self.device.name,
            "pci_bus_id": self.device.pci_bus_id,
            "compute_capability": self.device.compute_capability,
            "driver_version": self.device.driver_version,
            "total_mib": self.device.total_mib,
            "resource_variant": self.profile.resource_variant,
            "policy_source": self.policy_source,
        }


class AdaptiveGpuPolicies:
    """전체 VRAM으로 정책을 고른 뒤 그 정책의 실제 여유만 검사한다."""

    def __init__(
        self,
        profiles: Mapping[str | None, MainModelProfile],
        policy: dict,
        *,
        explicit_variant: str | None = None,
        explicit: bool = False,
        error: str | None = None,
    ):
        self.profiles = dict(profiles)
        self.policy = policy
        self.explicit_variant = explicit_variant
        self.explicit = explicit
        self.error = error
        self.minimum_compute = compute_capability(
            policy["gpu_minimum_compute_capability"]
        )
        if self.minimum_compute is None:
            raise ValueError("invalid GPU minimum compute capability")
        self.rules = policy["gpu_resource_policies"]
        previous = math.inf
        if not isinstance(self.rules, list) or not self.rules:
            raise ValueError("GPU resource policies must be non-empty")
        for rule in self.rules:
            if set(rule) != {"minimum_total_mib", "resource_variant"}:
                raise ValueError("invalid GPU resource policy rule")
            minimum = rule["minimum_total_mib"]
            if type(minimum) is not int or not 0 < minimum < previous:
                raise ValueError(
                    "GPU resource policies must have descending positive memory thresholds"
                )
            previous = minimum
            if self.profiles and rule["resource_variant"] not in self.profiles:
                raise ValueError("unknown GPU resource policy rule")
        if self.error is None and explicit and explicit_variant not in self.profiles:
            self.error = "GPU_RESOURCE_POLICY_UNAVAILABLE"

    def choose(
        self, snapshot: HostResourceSnapshot
    ) -> tuple[GpuAssignment | None, str | None]:
        if self.error:
            return None, self.error
        if snapshot.gpu_observation_error:
            return None, "GPU_OBSERVATION_UNAVAILABLE"
        reason = "GPU_MEMORY_INSUFFICIENT"
        blocked_assignment = None
        for device in snapshot.gpus:
            if not valid_gpu_uuid(device.uuid):
                reason = "GPU_IDENTITY_UNAVAILABLE"
                continue
            capability = compute_capability(device.compute_capability)
            if capability is None:
                reason = "GPU_COMPATIBILITY_UNKNOWN"
                continue
            if capability < self.minimum_compute:
                reason = "GPU_COMPATIBILITY_UNSUPPORTED"
                continue
            if self.explicit:
                variant = self.explicit_variant
            else:
                rule = next(
                    (
                        r
                        for r in self.rules
                        if device.total_mib >= r["minimum_total_mib"]
                    ),
                    None,
                )
                if rule is None:
                    continue
                variant = rule["resource_variant"]
            profile = self.profiles.get(variant)
            if profile is None:
                reason = "GPU_RESOURCE_POLICY_UNAVAILABLE"
                continue
            # 같은 장치의 여유가 부족해도 더 작은 정책으로 바꾸지 않는다.
            if device_fits(device, profile, self.policy):
                return GpuAssignment(
                    device, profile, "operator" if self.explicit else "memory_class"
                ), None
            if blocked_assignment is None:
                blocked_assignment = GpuAssignment(
                    device, profile, "operator" if self.explicit else "memory_class"
                )
        return (
            (blocked_assignment, "GPU_MEMORY_INSUFFICIENT")
            if blocked_assignment
            else (None, reason)
        )

    def restore(self, value: object) -> GpuAssignment | None:
        if (
            not isinstance(value, dict)
            or not valid_gpu_uuid(value.get("uuid"))
            or "resource_variant" not in value
            or (
                value["resource_variant"] is not None
                and not isinstance(value["resource_variant"], str)
            )
        ):
            return None
        profile = self.profiles.get(value.get("resource_variant"))
        if (
            profile is None
            or not isinstance(value.get("policy_source"), str)
            or value["policy_source"]
            not in {
                "operator",
                "memory_class",
            }
        ):
            return None
        total = value.get("total_mib")
        if type(total) is not int or total <= 0:
            return None
        # 보존된 식별은 정책 복원용이다. 실행·Gate 개방은 새 관측과 Canary를 요구한다.
        try:
            device = gpu_from_mapping({**value, "index": 0, "free_mib": 0})
        except (ValueError, TypeError):
            return None
        return GpuAssignment(device, profile, value["policy_source"])
