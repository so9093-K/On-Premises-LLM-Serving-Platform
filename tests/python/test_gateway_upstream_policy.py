"""Gateway가 비공개 제어 파라미터를 upstream으로 누출하지 않는 계약."""

from __future__ import annotations

from ai_model_serving.services.gateway_service import normalize_embedding_request_for_runtime


def test_gateway_drops_declared_parameters_without_mutating_request() -> None:
    original = {"model": "embed", "input": ["sample"], "user": "caller-123"}
    upstream = normalize_embedding_request_for_runtime(
        original,
        {"drop_upstream_parameters": ["user"]},
    )
    assert upstream == {"model": "embed", "input": ["sample"]}
    assert original["user"] == "caller-123"


def test_gateway_keeps_supported_embedding_parameters() -> None:
    original = {"model": "embed", "input": "sample", "dimensions": 256}
    assert normalize_embedding_request_for_runtime(original, None) == original
