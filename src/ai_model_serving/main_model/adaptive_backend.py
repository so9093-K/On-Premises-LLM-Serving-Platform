"""명시적으로 선택한 자동 배포의 CPU/GPU 실행 어댑터."""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from dataclasses import replace
from typing import Awaitable, Callable

import httpx

from ..host_resource_probe import (
    GpuMemory,
    HostResourceSnapshot,
    available_memory_mib,
    gpu_from_mapping,
)
from .catalog import MainModelCatalog, MainModelProfile
from .adaptive_gpu import (
    AdaptiveGpuPolicies,
    GpuAssignment,
    compute_capability,
    device_fits,
)
from .cpu import prepare_cpu_model
from .docker_backend import DockerMainModelBackend


class AdaptiveResourceReader:
    """고정 내부 서비스의 신선한 관측만 GPU Admission 입력으로 사용한다."""

    def __init__(self, url: str, token: str, maximum_age_seconds: float = 15):
        self.url = url
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        self.maximum_age_seconds = maximum_age_seconds

    async def __call__(self) -> HostResourceSnapshot:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(
                    self.url + "/snapshot", headers=self.headers
                )
                response.raise_for_status()
                data = response.json()
            observed = data["observed_at"]
            if (
                type(observed) not in (float, int)
                or not math.isfinite(observed)
                or not 0 <= time.time() - observed <= self.maximum_age_seconds
            ):
                raise ValueError("stale resource observation")
            gpus = []
            for row in data["gpus"]:
                gpus.append(gpu_from_mapping(row))
            uuids = [g.uuid for g in gpus if g.uuid is not None]
            if len({g.index for g in gpus}) != len(gpus) or len(set(uuids)) != len(
                uuids
            ):
                raise ValueError("ambiguous GPU observation")
            ram = data["ram_available_mib"]
            if ram is not None and (type(ram) is not int or ram < 0):
                raise ValueError("invalid CPU RAM observation")
            if data.get("gpu_observation_error"):
                gpus = []
            return HostResourceSnapshot(
                tuple(gpus), ram, data.get("gpu_observation_error")
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return HostResourceSnapshot(
                (), available_memory_mib(), "GPU_MEMORY_OBSERVATION_FAILED"
            )


def fitting_gpu(
    snapshot: HostResourceSnapshot, profile: MainModelProfile, policy: dict
) -> GpuMemory | None:
    """장치별 여유와 프로필 예약량을 검사하며 GPU 간 여유를 합산하지 않는다."""
    if snapshot.gpu_observation_error:
        return None
    return next(
        (gpu for gpu in snapshot.gpus if device_fits(gpu, profile, policy)), None
    )


class AdaptiveDockerBackend(DockerMainModelBackend):
    def __init__(
        self,
        *args,
        config_root: Path,
        cpu_cache_dir: Path,
        resource_reader: Callable[[], Awaitable[HostResourceSnapshot]],
        selection_policy: dict,
        gpu_policies: AdaptiveGpuPolicies,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.config_root = config_root
        self.cpu_cache_dir = cpu_cache_dir
        self.resource_reader = resource_reader
        self.selection_policy = selection_policy
        self.gpu_policies = gpu_policies
        self.gpu_assignment: GpuAssignment | None = None
        self.gpu_uuid: str | None = None

    def bind_gpu(self, assignment: GpuAssignment) -> None:
        self.gpu_assignment = assignment
        self.gpu_uuid = assignment.device.uuid

    async def _admit_gpu(self, profile: MainModelProfile) -> None:
        observed = await self.resource_reader()
        assignment = self.gpu_assignment
        if (
            assignment is None
            or assignment.profile.command != profile.command
            or assignment.profile.image != profile.image
        ):
            raise RuntimeError("GPU_ASSIGNMENT_UNAVAILABLE")
        device = next(
            (g for g in observed.gpus if g.uuid == assignment.device.uuid), None
        )
        if observed.gpu_observation_error or device is None:
            raise RuntimeError("GPU_IDENTITY_UNAVAILABLE")
        # 후보 UUID와 자원 정책을 고정하며 다른 장치나 작은 정책으로 조용히 옮기지 않는다.
        capability = self.gpu_policies.minimum_compute
        current_compute = compute_capability(device.compute_capability)
        if current_compute is None or current_compute < capability:
            raise RuntimeError("GPU_COMPATIBILITY_UNSUPPORTED")
        if not device_fits(device, profile, self.selection_policy):
            raise RuntimeError("GPU_MEMORY_ADMISSION_BLOCKED")
        if not self.gpu_policies.explicit:
            rule = next(
                (
                    r
                    for r in self.gpu_policies.rules
                    if device.total_mib >= r["minimum_total_mib"]
                ),
                None,
            )
            if rule is None or rule["resource_variant"] != profile.resource_variant:
                raise RuntimeError("GPU_RESOURCE_POLICY_CHANGED")
        self.gpu_uuid = device.uuid

    async def validate(
        self, catalog: MainModelCatalog, profile: MainModelProfile
    ) -> None:
        await super().validate(catalog, profile)
        if profile.runtime_backend == "llama-cpp":
            return
        snapshot = await self.resource_reader()
        runtime = await self.observe_runtime(catalog)
        device = next(
            (g for g in snapshot.gpus if g.uuid == runtime.get("gpu_device_uuid")), None
        )
        if (
            snapshot.gpu_observation_error
            or device is None
            or self.gpu_assignment is None
            or device.uuid != self.gpu_assignment.device.uuid
            or device.free_mib < self.selection_policy["gpu_pressure_free_mib"]
        ):
            raise RuntimeError("GPU_REVALIDATION_RESOURCE_UNSAFE")

    async def prepare(
        self, catalog: MainModelCatalog, profile: MainModelProfile
    ) -> None:
        if profile.runtime_backend == "llama-cpp":
            await asyncio.to_thread(
                prepare_cpu_model,
                config_root=self.config_root,
                output_root=self.cpu_cache_dir,
            )
        else:
            await self._admit_gpu(profile)
            await super().prepare(catalog, profile)

    async def replace(
        self, catalog: MainModelCatalog, profile: MainModelProfile
    ) -> None:
        # Drain·다운로드 뒤 변경된 자원 상태도 실행 직전에 다시 확인한다.
        if profile.runtime_backend == "llama-cpp":
            await self.prepare(catalog, profile)
        else:
            await self._admit_gpu(profile)
        await super().replace(catalog, profile)


class ManagedDockerBackend(AdaptiveDockerBackend):
    """고정 GPU 정책은 기존 수동 전환, 자동 정책은 장치별 Admission을 사용한다."""

    automatic: Callable[[MainModelProfile | None], bool] = lambda self, profile=None: False

    async def observe_runtime(self, catalog):
        return await super().observe_runtime(replace(catalog, runtime={**catalog.runtime, "adaptive": True}))

    async def prepare(self, catalog, profile):
        if profile.runtime_backend == "llama-cpp" or self.automatic(profile):
            await super().prepare(catalog, profile)
        else:
            self.gpu_uuid = None
            await DockerMainModelBackend.prepare(self, catalog, profile)

    async def replace(self, catalog, profile):
        if profile.runtime_backend == "llama-cpp" or self.automatic(profile):
            await super().replace(catalog, profile)
        else:
            self.gpu_uuid = None
            await DockerMainModelBackend.replace(self, catalog, profile)

    async def validate(self, catalog, profile):
        if self.automatic(profile):
            await super().validate(catalog, profile)
        else:
            await DockerMainModelBackend.validate(self, catalog, profile)
