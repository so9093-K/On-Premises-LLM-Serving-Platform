"""자기 배포의 포트 사용과 다른 checkout·프로세스의 점유를 구분한다."""
from pathlib import Path
import subprocess

from scripts.ops import host_ports


def test_port_ownership_considers_bind_address_and_foreign_containers(monkeypatch):
    monkeypatch.setattr(host_ports, "_published_ports", lambda: {
        9600: [("mine", "gateway", "127.0.0.1")],
        9610: [("mine", "grafana", "127.0.0.1"), ("other", "foreign", "192.0.2.10")],
        9620: [("other", "foreign", "192.0.2.10")],
    })
    monkeypatch.setattr(host_ports, "_owned_containers", lambda _: {"mine"})
    monkeypatch.setattr(host_ports, "_bindable", lambda port, bind: bind == "127.0.0.1" and port == 9620)
    holders = host_ports.port_holders(Path("/checkout"), {9600: "127.0.0.1", 9610: "0.0.0.0", 9620: "127.0.0.1", 9630: "127.0.0.1"})
    assert holders[9600].kind == "platform"
    assert holders[9610].kind == "container"
    assert holders[9620].kind == "free"
    assert holders[9630].kind == "process"
    # 자기 Gateway를 loopback에서 LAN 공개로 바꾸는 경우도 make up이 컨테이너를 교체한다.
    assert host_ports.port_holders(Path("/checkout"), {9600: "0.0.0.0"})[9600].kind == "platform"


def test_docker_publication_parser_keeps_ipv4_and_ipv6_addresses(monkeypatch):
    monkeypatch.setattr(host_ports.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0,
                            "mine\tgateway\t0.0.0.0:9600->9600/tcp, [::]:9600->9600/tcp, [::1]:9610->3000/tcp\n"))
    actual = host_ports._published_ports()
    assert {address for _, _, address in actual[9600]} == {"0.0.0.0", "::"}
    assert actual[9610] == [("mine", "gateway", "::1")]
