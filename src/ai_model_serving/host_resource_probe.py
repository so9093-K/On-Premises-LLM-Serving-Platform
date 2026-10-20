"""Host GPU 실측과 CPU RAM을 읽고 정해진 배포 후보를 판단한다.

GPU/CPU 관측은 계획 입력이다. 실제 엔진 호환성 및 모델 로딩 성공을 보장하지 않는다.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GpuMemory:
    index: int
    total_mib: int
    free_mib: int


@dataclass(frozen=True)
class HostResourceSnapshot:
    gpus: tuple[GpuMemory, ...]
    ram_available_mib: int | None
    gpu_observation_error: str | None = None


def available_memory_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_host_resource_snapshot() -> HostResourceSnapshot:
    available_ram = available_memory_mib()
    if not shutil.which("nvidia-smi"):
        return HostResourceSnapshot((), available_ram, "NVIDIA_TOOL_UNAVAILABLE")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=3,
        )
        records: list[GpuMemory] = []
        for raw in result.stdout.splitlines():
            if not raw.strip():
                continue
            parts = [value.strip() for value in raw.split(",")]
            if len(parts) != 3:
                raise ValueError("unexpected nvidia-smi CSV fields")
            gpu = GpuMemory(*map(int, parts))
            if gpu.index < 0 or gpu.total_mib <= 0 or not (0 <= gpu.free_mib <= gpu.total_mib):
                raise ValueError("invalid GPU memory measurement")
            records.append(gpu)
        if not records or len({gpu.index for gpu in records}) != len(records):
            raise ValueError("GPU observation is missing or ambiguous")
        return HostResourceSnapshot(tuple(records), available_ram)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return HostResourceSnapshot((), available_ram, "GPU_MEMORY_OBSERVATION_FAILED")
