"""새 품질 실행 체계의 최소 Python 행동 검사."""

from __future__ import annotations

import pytest

from ai_model_serving.main_model.execution_policy import resolve_execution_policy


def test_explicit_execution_policy_is_respected() -> None:
    assert resolve_execution_policy({}, {"MAIN_MODEL_EXECUTION_POLICY": "cpu"}) == "cpu"


def test_default_execution_policy_prefers_recovery() -> None:
    assert resolve_execution_policy({}, {}) == "fallback"


def test_invalid_execution_policy_fails() -> None:
    with pytest.raises(ValueError, match="invalid MAIN_MODEL_EXECUTION_POLICY"):
        resolve_execution_policy({}, {"MAIN_MODEL_EXECUTION_POLICY": "invalid"})
