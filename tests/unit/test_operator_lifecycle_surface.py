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
