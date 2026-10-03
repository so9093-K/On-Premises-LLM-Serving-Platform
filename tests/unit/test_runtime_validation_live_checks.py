from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.validation.runtime.live_checks import LiveRuntimeChecks


class _Registry:
    def public_logical_ids(self) -> list[str]:
        return ["local-main", "risk-prompt"]

    def runtime_service(self, key: str) -> SimpleNamespace:
        served = "local-main" if key == "main_llm" else key
        return SimpleNamespace(served_model_name=served)


class _Http:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def json(self, method: str, url: str, payload=None, **kwargs):
        self.calls.append((method, url, payload))
        if url.endswith("/v1/models"):
            return (
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "local-main",
                            "object": "model",
                            "created": 1,
                            "owned_by": "local",
                            "backend": "vllm",
                            "capabilities": ["chat.completions"],
                            "input_modalities": ["text", "image", "audio", "video"],
                            "request_parameters": {},
                            "request_limits": {},
                        }
                    ],
                },
                1,
            )
        if url.endswith("/models"):
            return 200, {"data": [{"id": "local-main"}]}, 1
        return (
            200,
            {
                "object": "chat.completion",
                "model": "local-main",
                "choices": [{"message": {"content": "OK"}}],
            },
            1,
        )

    def text(self, url: str, **kwargs):
        self.calls.append(("GET", url, None))
        return 200, "vllm:requests_running 0\n", 1


def _checks() -> tuple[LiveRuntimeChecks, _Http]:
    config = SimpleNamespace(
        root=Path("."),
        gateway_base="http://gateway",
        risk_base="http://risk",
        prometheus_base="http://prometheus",
        grafana_base="http://grafana",
        vllm_bases={"main_llm": "http://main/v1"},
        expected_vllm_version="0.30.0",
        expected_main_image_digest=None,
        model_serving={
            "models": {
                "main_llm": {
                    "served_model_name": "local-main",
                }
            }
        },
    )
    http = _Http()
    return (
        LiveRuntimeChecks(
            config=config,
            registry=_Registry(),
            monitoring={},
            http=http,
        ),
        http,
    )


def test_models_check_records_the_main_model_input_modalities() -> None:
    checks, _ = _checks()

    models = checks.check_models()

    assert models.passed
    assert models.details["main_model_input_modalities"] == [
        "text",
        "image",
        "audio",
        "video",
    ]


def test_main_runtime_artifact_records_observed_engine_and_digest() -> None:
    checks, http = _checks()
    original_json = http.json

    def json_with_artifact(method: str, url: str, payload=None, **kwargs):
        if url.endswith("/admin/main-model"):
            assert kwargs.get("admin") is True
            return 200, {"observed_runtime": {
                "status": "ready",
                "profile_id": "gemma4-12b-unified-fp8",
                "image_ref": "registry.example/vllm@sha256:" + "a" * 64,
                "image_id": "sha256:" + "b" * 64,
                "image_digest": "sha256:" + "a" * 64,
                "runtime_engine": {"name": "vllm", "version": "0.30.0"},
            }}, 1
        return original_json(method, url, payload, **kwargs)

    http.json = json_with_artifact
    result = checks.check_main_runtime_artifact()

    assert result.passed
    assert result.details["runtime_engine"] == {"name": "vllm", "version": "0.30.0"}
    assert result.details["image_digest"] == "sha256:" + "a" * 64


def test_main_runtime_artifact_rejects_wrong_engine_or_candidate_digest() -> None:
    checks, http = _checks()
    observed_digest = "sha256:" + "a" * 64

    def artifact_response(version: str):
        return 200, {"observed_runtime": {
            "status": "ready",
            "profile_id": "gemma4-e4b-it",
            "image_ref": "registry.example/vllm@" + observed_digest,
            "image_id": observed_digest,
            "image_digest": observed_digest,
            "runtime_engine": {"name": "vllm", "version": version},
        }}, 1

    http.json = lambda *args, **kwargs: artifact_response("0.25.1")
    assert checks.check_main_runtime_artifact().failed

    checks.config.expected_main_image_digest = "sha256:" + "b" * 64
    http.json = lambda *args, **kwargs: artifact_response("0.30.0")
    result = checks.check_main_runtime_artifact()
    assert result.failed
    assert result.details["expected_image_digest"] == "sha256:" + "b" * 64


def test_tool_auto_requires_a_parsed_function_call_with_json_arguments() -> None:
    checks, http = _checks()

    def response(arguments: str, finish_reason: str = "tool_calls"):
        return 200, {"choices": [{
            "finish_reason": finish_reason,
            "message": {"tool_calls": [{
                "type": "function",
                "function": {
                    "name": "get_runtime_answer",
                    "arguments": arguments,
                },
            }]},
        }]}, 1

    def good_response(method: str, url: str, payload):
        http.calls.append((method, url, payload))
        return response('{"topic":"runtime_validation"}')

    http.json = good_response
    assert checks.check_tool_auto().passed
    assert http.calls[-1][2]["tool_choice"] == "auto"

    http.json = lambda *args, **kwargs: response("not json")
    assert checks.check_tool_auto().failed
    http.json = lambda *args, **kwargs: response('{"topic":"runtime_validation"}', "stop")
    assert checks.check_tool_auto().failed


def test_media_canaries_use_checked_in_data_fixtures() -> None:
    checks, http = _checks()

    image = checks.check_chat_image()
    audio = checks.check_chat_audio()
    video = checks.check_chat_video()

    assert image.passed and audio.passed and video.passed

    image_part = http.calls[-3][2]["messages"][0]["content"][1]
    audio_part = http.calls[-2][2]["messages"][0]["content"][1]
    video_part = http.calls[-1][2]["messages"][0]["content"][1]

    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert audio_part["type"] == "input_audio"
    assert audio_part["input_audio"]["format"] == "m4a"
    assert audio_part["input_audio"]["data"]
    assert video_part["type"] == "video_url"
    assert video_part["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_vllm_metrics_use_app_root_not_openai_v1_prefix() -> None:
    checks, http = _checks()

    result = checks.scrape_vllm_metrics(
        "main_llm",
        "http://main/v1",
        ["vllm:requests_running"],
    )

    assert result.passed
    assert http.calls[-1][1] == "http://main/metrics"
