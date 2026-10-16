"""Docker 또는 배포 대상과 독립된 물리 GPU 자원 식별자.

하나의 자원 범위는 호스트 전체 VRAM이 아니라 개별 GPU의 예약 단위다.
실제 Host/Device 탐지가 구현되기 전까지 기존 단일 GPU 배포는
Controller 로컬 호환 범위를 사용하며, 이를 실제 탐지한 GPU로 표시하지 않는다.
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


# 기존 단일 GPU Docker 배포를 위한 호환성 투영이다.
# 실제 다중 장치 Inventory는 별도의 Host/Device 식별자를 제공해야 한다.
CONTROLLER_LOCAL_GPU = GpuResourceId("controller-local", "managed-gpu")
