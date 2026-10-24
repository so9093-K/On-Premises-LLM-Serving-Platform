"""관리형 모델 목록은 Controller가 검증한 정책만 현재 실행 정보로 광고한다."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_model_serving.api.routers.gateway_inference import build_router
from ai_model_serving.services.runtime_controller_client import RuntimeControllerUnavailableError


def _settings(*, managed: bool = True):
    catalog_policy = {
        "max_output_tokens": 4096,
        "request_limits": {"max_model_len": 8192, "input_modalities": ["text"]},
        "request_parameter_policy": {"supported_parameters": ["max_tokens"]},
    }
    return SimpleNamespace(
        public_models=(
            {
                "id": "local-main", "object": "model", "created": 1,
                "owned_by": "platform", "backend": "vllm-cuda",
                "display_name": "기본 GPU", "upstream_model_id": "stale-gpu",
                "context_window": 8192,
                "capabilities": [
                    "chat.completions", "responses", "chat.completions.vision",
                    "chat.completions.tools",
                ],
                "input_modalities": ["text", "image"],
                "request_parameters": {"max_tokens": {"max": 4096}},
                "request_limits": {"image": {"max_count": 2}},
            },
            {
                "id": "local-embed", "object": "model", "created": 1,
                "owned_by": "platform", "backend": "vllm-cuda",
                "capabilities": ["embeddings"], "request_parameters": {},
            },
        ),
        deployment_target=SimpleNamespace(
            control_mode="runtime_controller" if managed else "static"
        ),
        default_main_model_gateway_policy=catalog_policy,
        feature_enabled=lambda name: name == "chat",
        runtime=lambda key: SimpleNamespace(
            model="local-main", allowed_input_modalities=("text",)
        ),
    )


class Controller:
    def __init__(self, snapshot=None, *, fail: bool = False):
        self.snapshot = snapshot
        self.fail = fail

    async def main_model(self, *, observed: bool = True):
        assert observed is False
        if self.fail:
            raise RuntimeControllerUnavailableError("connection refused")
        return self.snapshot


async def _models(settings, controller):
    # 목록 endpoint 자체를 테스트해 Route→Controller→응답 투영을 함께 보호한다.
    with patch("ai_model_serving.api.routers.gateway_inference.ResponsesService"):
        router = build_router([], SimpleNamespace(), settings, runtime_controller=controller)
    endpoint = next(r.endpoint for r in router.routes if r.path == "/v1/models")
    return (await endpoint())["data"]


@pytest.mark.parametrize(("snapshot", "failure", "expected"), [
    (None, True, "controller_unavailable"),
    ({"gate": "closed", "active_profile": {
        "id": "limits-cpu", "runtime_backend": "llama-cpp",
    }}, False, "gate_closed"),
    ({"gate": "open", "active_profile": None}, False, "unverified"),
])
def test_unavailable_policy_does_not_advertise_stale_gpu_metadata(
    snapshot, failure, expected
):
    settings = _settings()
    result = asyncio.run(_models(settings, Controller(snapshot, fail=failure)))
    main, embedding = result
    assert main["serving_policy_status"] == expected
    assert main["backend"] == "unknown"
    assert main["request_parameters"] == {}
    assert main["capabilities"] == ["chat.completions", "responses"]
    for field in (
        "display_name", "upstream_model_id", "context_window",
        "input_modalities", "request_limits",
    ):
        assert field not in main
    assert embedding == settings.public_models[1]


def test_current_policy_is_advertised_only_with_open_gate_and_active_profile():
    active = {
        "id": "limits-cpu",
        "display_name": "CPU 사용자 한도",
        "upstream_model_id": "Qwen3",
        "runtime_backend": "llama-cpp",
        "capabilities": {"deployed_input": ["text"]},
        "gateway_policy": {
            "max_output_tokens": 2048,
            "request_limits": {"max_model_len": 16384, "input_modalities": ["text"]},
            "request_parameter_policy": {"supported_parameters": ["max_tokens"]},
        },
    }
    result = asyncio.run(_models(_settings(), Controller({
        "gate": "open", "active_profile": active,
    })))
    main = result[0]
    assert main["serving_policy_status"] == "active"
    assert main["backend"] == "llama-cpp"
    assert main["context_window"] == 16384
    assert main["display_name"] == "CPU 사용자 한도"
    assert main["request_parameters"]["max_tokens"]["max"] == 2048
    assert "chat.completions.vision" not in main["capabilities"]


def test_missing_controller_client_marks_managed_policy_unavailable():
    main, embedding = asyncio.run(_models(_settings(), None))
    assert main["serving_policy_status"] == "controller_unavailable"
    assert main["backend"] == "unknown"
    assert "context_window" not in main
    assert embedding["id"] == "local-embed"


def test_static_model_list_uses_declared_policy_without_controller():
    result = asyncio.run(_models(_settings(managed=False), None))
    main = result[0]
    assert "serving_policy_status" not in main
    assert main["backend"] == "vllm-cuda"
    assert main["context_window"] == 8192
    assert main["request_parameters"]["max_tokens"]["max"] == 4096
