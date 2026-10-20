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


def _available_ram() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_host_resource_snapshot() -> HostResourceSnapshot:
    available_ram = _available_ram()
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


def recommend_initial_target(
    snapshot: HostResourceSnapshot, policy: dict,
) -> tuple[str, str]:
    """GPU 후보는 장치별 총/여유 메모리를 모두 충족해야 한다.

    예약량, 실제 모델 Compatibility/Loading은 별도 Admission/Qualification이 판단한다.
    """
    limits = policy["startup"]
    min_total = int(limits["gpu_min_total_vram_mib"])
    min_free = int(limits["gpu_min_free_vram_mib"])
    min_ram = int(limits["cpu_min_available_ram_mib"])
    if any(value <= 0 for value in (min_total, min_free, min_ram)) or min_free > min_total:
        raise ValueError("invalid startup resource thresholds")
    for gpu in snapshot.gpus:
        if gpu.total_mib >= min_total and gpu.free_mib >= min_free:
            return str(limits["preferred_gpu_target"]), (
                f"GPU {gpu.index}: free {gpu.free_mib}MiB / total {gpu.total_mib}MiB; "
                "candidate only, real runtime admission required"
            )
    if snapshot.ram_available_mib is not None and snapshot.ram_available_mib >= min_ram:
        return str(limits["preferred_cpu_target"]), (
            f"GPU model candidate unavailable; CPU RAM available {snapshot.ram_available_mib}MiB"
        )
    return str(limits["no_inference_target"]), (
        "GPU model candidate unavailable; CPU available RAM insufficient or unobservable"
    )
