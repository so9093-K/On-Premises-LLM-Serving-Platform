"""포트 대역과 운영 명령: 어긋난 설정은 기동 전에 바로잡거나 멈추고, 실패는 원인과 다음 명령을 보여 준다."""
from __future__ import annotations

import pytest

from scripts import platform_cli
from scripts.config import setup_env


def test_sync_env_aligns_hand_edited_internal_urls_with_port_band(tmp_path, capsys):
    """서버에서 내부 주소만 9601·9605로 바꾸면 Gateway가 Main·Risk에 연결하지 못했다."""
    env = tmp_path / ".env"
    env.write_text(
        "BUILD_PROFILE=compose\nDEPLOYMENT_TARGET=linux-nvidia-dynamic\nPLATFORM_PORT_BASE=9400\n"
        "GATEWAY_PORT=9600\nMAIN_MODEL_BASE_URL=http://main-llm-vllm:9601/v1\n"
        "RISK_SIGNAL_SERVICE_BASE_URL=http://risk-signal-service:9605\n"
        "EMBEDDING_BASE_URL=http://embedding.example:9602/v1\n",
        encoding="utf-8",
    )
    assert setup_env.main(["--sync-env", "--env-file", str(env)]) == 0
    _, values = setup_env.parse_env_template(env)
    assert values["MAIN_MODEL_BASE_URL"] == "http://main-llm-vllm:9401/v1"
    assert values["RISK_SIGNAL_SERVICE_BASE_URL"] == "http://risk-signal-service:9405"
    # 외부 주소와 운영자가 지정한 Host 포트는 운영자 소유다.
    assert values["EMBEDDING_BASE_URL"] == "http://embedding.example:9602/v1"
    assert values["GATEWAY_PORT"] == "9600"
    assert "MAIN_MODEL_BASE_URL의 내부 포트를 바로잡습니다: 9601 → 9401" in capsys.readouterr().out


def test_runtime_secret_sync_replaces_stale_token_in_place(tmp_path, monkeypatch):
    """Compose secret은 파일 bind mount이므로 같은 inode에 써야 실행 중인 Prometheus가 읽는다."""
    monkeypatch.setattr(setup_env, "ROOT", tmp_path)
    secret = tmp_path / ".runtime/prometheus/admin_api_key"
    secret.parent.mkdir(parents=True)
    secret.write_text("stale-key\n", encoding="utf-8")
    inode = secret.stat().st_ino
    env = tmp_path / ".env"
    env.write_text("ADMIN_API_KEY=current-key\n", encoding="utf-8")
    assert setup_env.main(["--sync-runtime-secrets", "--output", str(env)]) == 0
    assert secret.read_text(encoding="utf-8") == "current-key\n"
    assert secret.stat().st_ino == inode


def test_up_stops_before_any_service_change_when_host_port_is_taken(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_cli, "ROOT", tmp_path)
    monkeypatch.setattr(platform_cli, "ENV_PATH", tmp_path / ".env")
    platform_cli.ENV_PATH.write_text(
        "BUILD_PROFILE=compose\nPLATFORM_PORT_BASE=9400\nMAIN_MODEL_EXECUTION_POLICY=gpu\n"
    )
    monkeypatch.setattr(platform_cli, "setup_target", lambda *args: True)
    import scripts.config.ports as ports
    # 9400·9500은 다른 프로그램이 쓰고 9600은 비어 있다.
    monkeypatch.setattr(ports, "host_port_conflicts", lambda values: (
        [] if values.get("PLATFORM_PORT_BASE") == "9600" else ["Gateway 9400: 다른 프로세스가 사용 중"]
    ))
    for step in ("ensure_target_artifacts", "start_core", "up_managed_cpu_first", "prepare_target", "up_target"):
        monkeypatch.setattr(platform_cli, step, lambda *a, _step=step, **k: pytest.fail(f"{_step} ran"))
    target = platform_cli.load_deployment_target(platform_cli.TARGETS_PATH, "linux-nvidia-dynamic")
    with pytest.raises(RuntimeError) as error:
        platform_cli.reconcile_up_target(
            target, main_profile=None, main_base_url=None, access_profile=None, confirm_access=False
        )
    message = str(error.value)
    assert "실행 중인 서비스는 바꾸지 않았습니다" in message
    assert "Gateway 9400: 다른 프로세스가 사용 중" in message
    assert "make up PORTS=9600" in message


def _status(monkeypatch, ready, *, values=None):
    monkeypatch.setattr(platform_cli, "_env_values", lambda: values or {"BUILD_PROFILE": "compose"})
    responses = iter([ready, (200, {"runtimes": [
        {"service_key": "embedding", "state": "stopped", "container_status": "created"},
    ]})])
    monkeypatch.setattr(platform_cli, "_gateway_json", lambda *args, **kwargs: next(responses))


def test_status_names_failed_dependency_endpoint_and_its_logs(monkeypatch, capsys):
    _status(monkeypatch, (503, {
        "status": "not_ready",
        "required_not_ready_dependencies": ["main_llm_vllm"],
        "dependencies": [{
            "name": "main_llm_vllm", "status": "not_ready",
            "endpoint": "http://main-llm-vllm:9601/v1/models",
            "message": "MODEL_UNAVAILABLE: Upstream unavailable: local-main",
        }],
    }))
    target = platform_cli.load_deployment_target(platform_cli.TARGETS_PATH, "linux-nvidia-dynamic")
    assert platform_cli.status_target(target) == 1
    output = capsys.readouterr().out
    assert "Gateway       NOT_READY  http://127.0.0.1:9400" in output
    assert "main_llm_vllm: MODEL_UNAVAILABLE: Upstream unavailable: local-main (http://main-llm-vllm:9601/v1/models)" in output
    assert "make logs SERVICE=main-llm-vllm" in output
    assert "STOPPED / created · 필요할 때 Console에서 시작" in output


def test_status_explains_port_band_not_yet_applied(monkeypatch, capsys):
    values = {"BUILD_PROFILE": "compose", "PLATFORM_PORT_BASE": "9600"}
    monkeypatch.setattr(platform_cli, "_env_values", lambda: values)
    monkeypatch.setattr(platform_cli, "_gateway_json", lambda *args, **kwargs: (0, None))
    monkeypatch.setattr(
        platform_cli,
        "_gateway_container_problem",
        lambda values: ("실행 중인 Gateway는 Host 9400 포트를 사용합니다.", "make up"),
    )
    target = platform_cli.load_deployment_target(platform_cli.TARGETS_PATH, "linux-nvidia-dynamic")
    assert platform_cli.status_target(target) == 1
    output = capsys.readouterr().out
    assert "Gateway       UNAVAILABLE  http://127.0.0.1:9600" in output
    assert "실행 중인 Gateway는 Host 9400 포트를 사용합니다." in output
    assert output.rstrip().endswith("make up")


def test_readiness_timeout_reports_each_required_dependency(monkeypatch):
    monkeypatch.setattr(platform_cli, "_gateway_json", lambda *args, **kwargs: (503, {
        "required_not_ready_dependencies": ["main_llm_vllm", "risk-signal-service"],
        "dependencies": [
            {"name": "main_llm_vllm", "status": "not_ready", "message": "UPSTREAM_UNAVAILABLE",
             "endpoint": "http://main-llm-vllm:9601/v1/models"},
            {"name": "risk-signal-service", "status": "not_ready", "message": "UPSTREAM_UNAVAILABLE",
             "endpoint": "http://risk-signal-service:9605/ready"},
            {"name": "embedding_vllm", "status": "not_ready", "message": "MODEL_UNAVAILABLE"},
        ],
    }))
    message = str(platform_cli._readiness_timeout({}))
    assert "main_llm_vllm: UPSTREAM_UNAVAILABLE (http://main-llm-vllm:9601/v1/models)" in message
    assert "risk-signal-service: UPSTREAM_UNAVAILABLE (http://risk-signal-service:9605/ready)" in message
    assert "embedding_vllm" not in message
    assert "make logs SERVICE=main-llm-vllm" in message


@pytest.mark.parametrize(
    ("target", "url", "expected"),
    [
        # CPU Static의 llama.cpp는 대역 밖 고정 포트에서 수신한다.
        ("linux-cpu-managed", "http://cpu-main:8080/v1", "http://cpu-main:8080/v1"),
        # Metal Main은 Host에서 대역 포트로 수신한다.
        ("macos-metal-static", "http://host.docker.internal:9401/v1", "http://host.docker.internal:9601/v1"),
    ],
)
def test_runtime_host_alignment_only_applies_to_band_ports(target, url, expected):
    values = {"DEPLOYMENT_TARGET": target, "PLATFORM_PORT_BASE": "9600", "MAIN_MODEL_BASE_URL": url}
    changes = setup_env.managed_endpoint_changes(values)
    assert changes.get("MAIN_MODEL_BASE_URL", (url, url))[1] == expected


def test_fresh_cpu_static_env_keeps_cpu_runtime_port(tmp_path):
    out = tmp_path / ".env"
    assert setup_env.main([
        "--profile", "compose", "--output", str(out), "--deployment-target", "linux-cpu-managed",
    ]) == 0
    _, values = setup_env.parse_env_template(out)
    assert values["MAIN_MODEL_BASE_URL"] == "http://cpu-main:8080/v1"


def test_app_only_rerun_does_not_treat_own_processes_as_conflicts(tmp_path, monkeypatch):
    import os

    from scripts.config import ports
    from scripts.ops.host_ports import PortHolder

    monkeypatch.setattr(ports, "ROOT", tmp_path)
    (tmp_path / "run").mkdir()
    (tmp_path / "run/gateway.pid").write_text(str(os.getpid()))
    monkeypatch.setattr(ports, "port_holders", lambda root, mapping: {port: PortHolder("process") for port in mapping})
    values = {"BUILD_PROFILE": "local", "PLATFORM_PORT_BASE": "9400"}
    # Gateway는 이 checkout의 프로세스이고 Risk PID 파일은 없다.
    assert ports.host_port_conflicts(values) == ["Risk 9405: 다른 프로세스가 사용 중 (확인: ss -ltnp 'sport = :9405')"]
