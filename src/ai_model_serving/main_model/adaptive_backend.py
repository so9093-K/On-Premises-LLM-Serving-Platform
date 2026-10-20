"""명시적으로 선택한 자동 배포의 CPU/GPU 실행 어댑터."""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from ..host_resource_probe import GpuMemory, HostResourceSnapshot, available_memory_mib
from .catalog import MainModelCatalog, MainModelProfile
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
                index, total, free = (
                    row[k] for k in ("index", "total_mib", "free_mib")
                )
                if (
                    any(type(v) is not int for v in (index, total, free))
                    or index < 0
                    or total <= 0
                    or not 0 <= free <= total
                ):
                    raise ValueError("invalid GPU observation")
                gpus.append(GpuMemory(index, total, free))
            if len({g.index for g in gpus}) != len(gpus):
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
    if (
        snapshot.gpu_observation_error
        or not 0 < profile.vram_fraction <= policy["gpu_budget_ceiling"]
    ):
        return None
    for gpu in snapshot.gpus:
        required = math.ceil(gpu.total_mib * profile.vram_fraction) + int(
            policy["gpu_start_margin_mib"]
        )
        if (
            gpu.total_mib >= int(policy["gpu_minimum_total_mib"])
            and gpu.free_mib >= required
        ):
            return gpu
    return None


class AdaptiveDockerBackend(DockerMainModelBackend):
    def __init__(
        self,
        *args,
        config_root: Path,
        cpu_cache_dir: Path,
        resource_reader: Callable[[], Awaitable[HostResourceSnapshot]],
        selection_policy: dict,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.config_root = config_root
        self.cpu_cache_dir = cpu_cache_dir
        self.resource_reader = resource_reader
        self.selection_policy = selection_policy
        self.gpu_index: int | None = None

    async def _admit_gpu(self, profile: MainModelProfile) -> None:
        observed = await self.resource_reader()
        device = fitting_gpu(observed, profile, self.selection_policy)
        if device is None:
            raise RuntimeError("GPU_MEMORY_ADMISSION_BLOCKED")
        self.gpu_index = device.index

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
