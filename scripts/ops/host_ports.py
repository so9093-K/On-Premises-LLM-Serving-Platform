"""Host 공개 포트를 누가 사용 중인지 확인한다. 표준 라이브러리만 사용한다."""
from __future__ import annotations

import errno
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.ops.compose_ownership import owned_container_ids

_PUBLISHED = re.compile(r"(\[[0-9a-fA-F:]+\]|[0-9a-fA-F:.]+):(\d+)->")


@dataclass(frozen=True)
class PortHolder:
    # free: 비어 있음 · platform: 이 checkout의 컨테이너 · container: 다른 컨테이너 · process: 그 밖의 프로세스
    kind: str
    name: str = ""

    def describe(self, port: int) -> str:
        if self.kind == "platform":
            return f"이 플랫폼의 {self.name} 컨테이너가 사용 중 (make up이 새 설정으로 교체)"
        if self.kind == "container":
            return f"다른 Docker 컨테이너 {self.name}가 사용 중"
        if self.kind == "process":
            check = (f"lsof -nP -iTCP:{port} -sTCP:LISTEN" if sys.platform == "darwin"
                     else f"ss -ltnp 'sport = :{port}'")
            return f"다른 프로세스가 사용 중 (확인: {check})"
        return "사용 가능"


def _listening(port: int, bind: str) -> bool:
    family = socket.AF_INET6 if ":" in bind else socket.AF_INET
    target = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(bind, bind)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((target, port)) == 0


def _bindable(port: int, bind: str) -> bool:
    family = socket.AF_INET6 if ":" in bind else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind, port))
        except OSError as error:
            # 직전 정지로 남은 TIME_WAIT도 EADDRINUSE를 낸다. 실제 서버는 SO_REUSEADDR로 기동하므로
            # 연결을 받는 리스너가 없을 때만 비어 있다고 본다. SO_REUSEADDR 검사는 macOS에서
            # wildcard 리스너와의 충돌을 놓치므로 쓰지 않는다.
            return error.errno == errno.EADDRINUSE and not _listening(port, bind)
    return True


def _published_ports() -> dict[int, list[tuple[str, str, str]]]:
    """Host 포트 → (컨테이너 ID, 이름, bind 주소)."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"],
            text=True, capture_output=True, check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    published: dict[int, list[tuple[str, str, str]]] = {}
    for line in result.stdout.splitlines() if result.returncode == 0 else []:
        container, name, ports = (line.split("\t") + ["", ""])[:3]
        for address, port in set(_PUBLISHED.findall(ports)):
            published.setdefault(int(port), []).append((container, name, address.strip("[]")))
    return published


def _owned_containers(root: Path) -> set[str]:
    try:
        return {container[:12] for container in owned_container_ids(root)}
    except (OSError, RuntimeError):
        return set()


def port_holders(root: Path, ports: dict[int, str]) -> dict[int, PortHolder]:
    """`ports`는 Host 포트 → bind 주소다."""
    published = _published_ports()
    owned = _owned_containers(root) if published else set()
    holders: dict[int, PortHolder] = {}
    for port, bind in ports.items():
        containers = [item for item in published.get(port, [])
                      if item[2] == bind or item[2] in {"0.0.0.0", "::"} or bind in {"0.0.0.0", "::"}]
        foreign = next((name for container, name, _ in containers if container[:12] not in owned), None)
        # 겹치는 주소에 공개한 자기 컨테이너는 make up이 새 설정으로 교체하므로 충돌이 아니다.
        mine = next((name for container, name, _ in containers if container[:12] in owned), None)
        # 자기 컨테이너가 있더라도 같은 주소 범위에 타 checkout이 있으면 승계할 수 없다.
        if foreign:
            holders[port] = PortHolder("container", foreign)
        elif mine:
            holders[port] = PortHolder("platform", mine)
        elif _bindable(port, bind):
            holders[port] = PortHolder("free")
        else:
            holders[port] = PortHolder("process")
    return holders
