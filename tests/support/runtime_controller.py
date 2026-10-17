"""Runtime Controller 단위 테스트의 로컬 환경 구성 공통 진입점.

모든 호출에서 모듈을 reload하여 테스트 간 Runtime 전역 상태를 공유하지 않는다.
"""

from __future__ import annotations

import importlib


def load_runtime_controller(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIN_MODEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    monkeypatch.setenv("COMPOSE_PROJECT", "test-platform")
    import ai_model_serving.apps.runtime_controller as runtime_controller

    return importlib.reload(runtime_controller)

