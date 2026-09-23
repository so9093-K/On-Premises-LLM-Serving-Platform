from __future__ import annotations

from pathlib import Path

import pytest

from ai_model_serving import service_logging
from scripts import platform_cli
from scripts.ops import platform_logs


ROOT = Path(__file__).resolve().parents[2]


def test_public_operator_surface_is_intent_based() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "PUBLIC_TARGETS := up status down logs reset purge" in makefile
    for removed in (
        "setup",
        "build",
        "rebuild",
        "prepare",
        "down-all",
        "compose-up",
        "compose-config",
        "ready-local",
        "ready-full",
        "smoke",
        "compose-down",
        "compose-restart",
        "compose-logs",
        "compose-diagnostics",
        "clean",
        "help-all",
    ):
        assert f"\n{removed}:" not in makefile


def test_reset_preserves_expensive_reusable_artifacts() -> None:
    script = (ROOT / "scripts/ops/reset_all.sh").read_text(encoding="utf-8")

    assert '"$ROOT/model_cache"' not in script
    assert "project-built images" in script
    assert "repository-local model cache" in script
    assert '[[ "$BUILD_PROFILE" == "local" ]]' in script
    assert "stopping app-only host processes" in script


def test_purge_never_claims_global_cache_ownership() -> None:
    script = (ROOT / "scripts/ops/purge_all.sh").read_text(encoding="utf-8")

    assert "global Hugging Face cache" in script
    assert "daemon-wide BuildKit cache" in script
    assert "docker system prune" not in script


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


USER_FACING_LIFECYCLE_DOCS = (
    "README.md",
    "scripts/README.md",
    "docs/04_runtime_modes.md",
    "docs/05_configuration.md",
    "docs/07_local_dev_build.md",
    "docs/08_testing_validation.md",
    "docs/09_cicd.md",
    "docs/10_deployment.md",
    "docs/12_operations.md",
    "docs/13_change_guide.md",
    "docs/appendix.md",
)


def test_user_facing_docs_do_not_restore_removed_operator_aliases() -> None:
    import re

    removed = (
        "setup",
        "build",
        "rebuild",
        "prepare",
        "down-all",
        "compose-up",
        "compose-config",
        "ready-local",
        "ready-full",
        "smoke",
        "compose-down",
        "compose-restart",
        "compose-logs",
        "compose-diagnostics",
        "clean",
        "help-all",
    )
    patterns = {
        name: re.compile(rf"make {re.escape(name)}(?=\\s|$)")
        for name in removed
    }
    for relative in USER_FACING_LIFECYCLE_DOCS:
        content = (ROOT / relative).read_text(encoding="utf-8")
        for name, pattern in patterns.items():
            assert pattern.search(content) is None, f"{relative} restores make {name}"


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


def test_compose_diagnostic_timestamp_is_ascii_utc() -> None:
    script = (ROOT / "scripts/compose/compose_diagnostics.sh").read_text(encoding="utf-8")

    assert 'date -u +%Y%m%dT%H%M%SZ' in script
    assert "Â" not in script


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
