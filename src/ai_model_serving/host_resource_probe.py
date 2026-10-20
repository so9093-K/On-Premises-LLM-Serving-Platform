"""Host GPU 실측과 CPU RAM을 읽고 정해진 배포 후보를 판단한다.

GPU/CPU 관측은 계획 입력이다. 실제 엔진 호환성 및 모델 로딩 성공을 보장하지 않는다.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GpuMemory:
    index: int
    total_mib: int
    free_mib: int
    name: str | None = None
    uuid: str | None = None
    pci_bus_id: str | None = None
    compute_capability: str | None = None
    driver_version: str | None = None


def valid_gpu_uuid(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(
            r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
        )
        is not None
    )


def gpu_from_mapping(row: dict) -> GpuMemory:
    """관측 경계에서 메모리·Identity를 검증하며 알 수 없는 속성을 추측하지 않는다."""
    index, total, free = (row[k] for k in ("index", "total_mib", "free_mib"))
    if (
        any(type(v) is not int for v in (index, total, free))
        or index < 0
        or total <= 0
        or not 0 <= free <= total
    ):
        raise ValueError("invalid GPU memory observation")
    fields = {
        key: row.get(key)
        for key in (
            "name",
            "uuid",
            "pci_bus_id",
            "compute_capability",
            "driver_version",
        )
    }
    if any(
        value is not None and (not isinstance(value, str) or not value.strip())
        for value in fields.values()
    ):
        raise ValueError("invalid GPU identity observation")
    if fields["uuid"] is not None and not valid_gpu_uuid(fields["uuid"]):
        raise ValueError("invalid GPU UUID")
    if (
        fields["compute_capability"] is not None
        and re.fullmatch(r"[0-9]+\.[0-9]+", fields["compute_capability"]) is None
    ):
        raise ValueError("invalid GPU compute capability")
    return GpuMemory(index, total, free, **fields)


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
            [
                "nvidia-smi",
                "--query-gpu=index,name,uuid,pci.bus_id,compute_cap,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        records: list[GpuMemory] = []
        for parts in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            if not parts:
                continue
            if len(parts) != 8:
                raise ValueError("unexpected nvidia-smi CSV fields")
            index, name, uuid, bus, compute, total, free, driver = (
                value.strip() for value in parts
            )

            def optional(value):
                return (
                    None if value in {"N/A", "[N/A]", "[Not Supported]", ""} else value
                )

            records.append(
                gpu_from_mapping(
                    {
                        "index": int(index),
                        "total_mib": int(total),
                        "free_mib": int(free),
                        "name": optional(name),
                        "uuid": optional(uuid),
                        "pci_bus_id": optional(bus),
                        "compute_capability": optional(compute),
                        "driver_version": optional(driver),
                    }
                )
            )
        uuids = [gpu.uuid for gpu in records if gpu.uuid is not None]
        if (
            not records
            or len({gpu.index for gpu in records}) != len(records)
            or len(set(uuids)) != len(uuids)
        ):
            raise ValueError("GPU observation is missing or ambiguous")
        return HostResourceSnapshot(tuple(records), available_ram)
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ):
        return HostResourceSnapshot((), available_ram, "GPU_MEMORY_OBSERVATION_FAILED")
