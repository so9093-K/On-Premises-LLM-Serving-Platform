from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from ai_model_serving import service_logging
from scripts import platform_cli
from scripts.ops import platform_logs


ROOT = Path(__file__).resolve().parents[2]


def test_reset_and_purge_never_delete_shared_caches() -> None:
    # 되돌릴 수 없는 삭제만 막는다. reset은 model cache를, purge는 daemon 전체 자원을 건드리지 않는다.
    reset = (ROOT / "scripts/ops/reset_all.sh").read_text(encoding="utf-8")
    purge = (ROOT / "scripts/ops/purge_all.sh").read_text(encoding="utf-8")

    assert '"$ROOT/model_cache"' not in reset
    assert "docker system prune" not in purge


def test_structured_logs_hide_success_noise_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    (event_dir / "gateway.jsonl").write_text(
        '{"service":"gateway","route":"/health","status_code":200}\n'
        '{"service":"gateway","route":"/v1/chat/completions","status_code":503,'
        '"error_code":"MODEL_UNAVAILABLE"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(platform_logs, "REQUEST_EVENTS", event_dir)

    count = platform_logs._structured_events(20)

    output = capsys.readouterr().out
    assert count == 1
    assert "/v1/chat/completions" in output
    assert "/health" not in output


def test_log_level_env_controls_service_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    logger = service_logging.service_logger("operator-surface-test")

    assert logger.level == 40


def test_invalid_log_level_fails_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        service_logging.service_logger("operator-surface-invalid")


def test_local_image_match_requires_current_clean_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        returncode = 0
        stdout = (
            '{"org.opencontainers.image.revision":"abc",'
            '"ai_model_serving.source_state":"clean"}'
        )

    monkeypatch.setattr(platform_cli.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(platform_cli, "_source_provenance", lambda: ("abc", "clean"))

    assert platform_cli._local_image_matches_source("sha256:local") is True

    monkeypatch.setattr(platform_cli, "_source_provenance", lambda: ("abc", "dirty"))
    assert platform_cli._local_image_matches_source("sha256:local") is False


def test_platform_logs_main_accepts_explicit_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(platform_logs, "REQUEST_EVENTS", tmp_path / "missing-events")

    assert platform_logs.main([]) == 0
    assert "No structured application events found." in capsys.readouterr().out


def test_app_only_status_uses_process_health_instead_of_model_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = platform_cli.load_deployment_target(
        platform_cli.TARGETS_PATH,
        "linux-nvidia-dynamic",
    )
    monkeypatch.setattr(
        platform_cli,
        "_env_values",
        lambda: {
            "BUILD_PROFILE": "local",
            "ACCESS_PROFILE": "local",
        },
    )
    monkeypatch.setattr(
        platform_cli,
        "_gateway_probe",
        lambda values, path: ("http://127.0.0.1:9400/health", path == "/health"),
    )

    class Result:
        returncode = 0

    monkeypatch.setattr(platform_cli.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(
        platform_cli,
        "_gateway_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("app-only status must not require /ready")
        ),
    )

    assert platform_cli.status_target(target) == 0
    output = capsys.readouterr().out
    assert "Platform      READY" in output
    assert "Applications  READY" in output


def test_full_stack_status_fails_closed_on_bare_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = platform_cli.load_deployment_target(
        platform_cli.TARGETS_PATH,
        "linux-nvidia-dynamic",
    )
    monkeypatch.setattr(
        platform_cli,
        "_env_values",
        lambda: {
            "BUILD_PROFILE": "compose",
            "ACCESS_PROFILE": "local",
        },
    )
    responses = iter(
        [
            (503, {"status": "not_ready", "dependencies": []}),
            (200, {"runtimes": [], "topology": []}),
        ]
    )
    monkeypatch.setattr(
        platform_cli,
        "_gateway_json",
        lambda *args, **kwargs: next(responses),
    )

    assert platform_cli.status_target(target) == 1
    output = capsys.readouterr().out
    assert "Gateway       NOT_READY" in output
    assert "Gateway is not ready" in output


def test_access_change_plan_uses_visible_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BUILD_PROFILE=compose\n"
        "AUTH_MODE=local_open\n"
        "EXPOSURE_MODE=master_open\n"
        "EXPOSURE_AUDIENCE=private_lan\n",
        encoding="utf-8",
    )
    target = platform_cli.load_deployment_target(
        platform_cli.TARGETS_PATH,
        "linux-nvidia-dynamic",
    )
    visible: list[tuple[str, ...]] = []
    hidden: list[tuple[str, ...]] = []
    monkeypatch.setattr(platform_cli, "ENV_PATH", env_path)
    monkeypatch.setattr(
        platform_cli,
        "_run",
        lambda *command, env=None: visible.append(command),
    )
    monkeypatch.setattr(
        platform_cli,
        "_run_step",
        lambda _label, *command, env=None: hidden.append(command),
    )

    assert platform_cli.setup_target(target, None, None, "private", False) is False
    assert len(visible) == 1
    assert hidden == []


def test_raw_logs_include_native_metal_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app_logs = tmp_path / "logs"
    metal_logs = tmp_path / "metal"
    app_logs.mkdir()
    metal_logs.mkdir()
    (metal_logs / "runtime.log").write_text("metal-ready\n", encoding="utf-8")
    monkeypatch.setattr(platform_logs, "ROOT", tmp_path)
    monkeypatch.setattr(platform_logs, "LOCAL_LOGS", app_logs)
    monkeypatch.setattr(platform_logs, "NATIVE_METAL_LOGS", metal_logs)
    monkeypatch.setattr(platform_logs, "_owned_containers", lambda service=None: [])

    assert platform_logs._raw_logs("metal", tail=10, follow=False) == 0
    output = capsys.readouterr().out
    assert "runtime.log" in output
    assert "metal-ready" in output


def test_compose_mutation_rejects_foreign_checkout_but_allows_current_checkout(
    tmp_path: Path,
) -> None:
    current_compose_dir = tmp_path / "repo-a" / "ops" / "compose"
    foreign_compose_dir = tmp_path / "repo-b" / "ops" / "compose"
    current_compose_dir.mkdir(parents=True)
    foreign_compose_dir.mkdir(parents=True)
    compose_file = current_compose_dir / "full-stack.private-network.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"ps\" ]; then echo container-1; exit 0; fi\n"
        "if [ \"$1\" = \"inspect\" ]; then printf '%s\\n' \"$FAKE_DOCKER_WORKING_DIR\"; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "PYTHON_BIN": sys.executable,
            "COMPOSE_FILE": str(compose_file),
            "COMPOSE_PROJECT_NAME": "shared-project",
        }
    )
    command = (
        'source scripts/lib/compose_context.sh; '
        'compose_context_init "$PWD"; '
        'compose_context_assert_mutation_safe'
    )

    foreign_env = dict(env)
    foreign_env["FAKE_DOCKER_WORKING_DIR"] = str(foreign_compose_dir)
    rejected = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=foreign_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "refusing to mutate project 'shared-project'" in rejected.stderr

    current_env = dict(env)
    current_env["FAKE_DOCKER_WORKING_DIR"] = str(current_compose_dir)
    allowed = subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env=current_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert allowed.returncode == 0
