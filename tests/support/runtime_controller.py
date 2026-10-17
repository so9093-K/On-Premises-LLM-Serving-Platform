"""Runtime Controller 테스트는 importlib.reload 없이 독립 App을 생성한다."""

from __future__ import annotations

from ai_model_serving.apps.runtime_controller import create_runtime_controller_app


def load_runtime_controller(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    return create_runtime_controller_app().state.controller
