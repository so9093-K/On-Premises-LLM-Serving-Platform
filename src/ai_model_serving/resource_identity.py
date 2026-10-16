"""Physical resource identity, independent of Docker and deployment targets.

A scope names one GPU reservation domain, not an entire host's aggregated VRAM.
The controller-local scope preserves the existing one-GPU runtime until discovery
provides a real host/device identity. It must never be advertised as a discovered GPU.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True, order=True)
class GpuResourceId:
    host_id: str
    device_id: str

    def __post_init__(self) -> None:
        for field, value in (("host_id", self.host_id), ("device_id", self.device_id)):
            if not isinstance(value, str) or not _ID_RE.fullmatch(value):
                raise ValueError(f"{field} must be a non-empty stable resource identifier")


# Compatibility projection for the existing single-GPU Docker deployment.
# A real fleet inventory must supply its own host and device identifiers.
CONTROLLER_LOCAL_GPU = GpuResourceId("controller-local", "managed-gpu")
