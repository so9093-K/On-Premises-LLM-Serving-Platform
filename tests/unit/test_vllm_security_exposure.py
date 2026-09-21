from __future__ import annotations

import pytest

from ai_model_serving.contracts.chat_request import validate_chat_request
from ai_model_serving.contracts.embedding import validate_embedding_request
from ai_model_serving.contracts.responses import validate_responses_request
from ai_model_serving.errors import ServiceError


_STRICT_PARAMETER_POLICY = {
    "allow_unlisted_parameters": False,
    "supported_parameters": [],
}


def test_negative_embedding_token_ids_never_reach_vllm() -> None:
    """GHSA-25q3-v2hm-8vpf: public embeddings accept text, not caller token IDs."""
    with pytest.raises(ServiceError) as exc:
        validate_embedding_request(
            {"model": "local-embed", "input": [[-1, 1879]]},
            expected_model="local-embed",
            request_parameter_policy=_STRICT_PARAMETER_POLICY,
        )

    assert exc.value.status_code == 422
    assert exc.value.param == "input"
    assert "string or non-empty string array" in str(exc.value)


@pytest.mark.parametrize(
    ("surface", "validator", "payload", "kwargs"),
    [
        (
            "chat",
            validate_chat_request,
            {
                "model": "local-main",
                "messages": [{"role": "user", "content": "hello"}],
                "cache_salt": "attacker-controlled",
            },
            {
                "expected_model": "local-main",
                "request_parameter_policy": _STRICT_PARAMETER_POLICY,
            },
        ),
        (
            "embedding",
            validate_embedding_request,
            {
                "model": "local-embed",
                "input": "hello",
                "cache_salt": "attacker-controlled",
            },
            {
                "expected_model": "local-embed",
                "request_parameter_policy": _STRICT_PARAMETER_POLICY,
            },
        ),
        (
            "responses",
            validate_responses_request,
            {
                "model": "local-main",
                "input": "hello",
                "cache_salt": "attacker-controlled",
            },
            {
                "expected_model": "local-main",
            },
        ),
    ],
)
def test_cache_salt_is_not_a_gateway_request_surface(
    surface: str,
    validator,
    payload: dict,
    kwargs: dict,
) -> None:
    """GHSA-wpww-v874-ph2p: Gateway never forwards caller cache_salt to vLLM."""
    with pytest.raises(ServiceError) as exc:
        validator(payload, **kwargs)

    assert exc.value.status_code == 422, surface
    assert exc.value.param == "cache_salt", surface


@pytest.mark.parametrize(
    ("part", "kwargs", "expected_param"),
    [
        (
            {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
            {
                "allowed_input_modalities": ("text", "image"),
                "max_image_inputs": 1,
                "allowed_image_url_schemes": ("data",),
            },
            "image_url.url",
        ),
        (
            {"type": "video_url", "video_url": {"url": "https://example.invalid/video.mp4"}},
            {
                "allowed_input_modalities": ("text", "video"),
                "max_video_inputs": 1,
                "allowed_video_url_schemes": ("data",),
            },
            "video_url",
        ),
    ],
)
def test_remote_media_urls_never_reach_vllm(
    part: dict,
    kwargs: dict,
    expected_param: str,
) -> None:
    """GHSA-p6g9-7v3x-m8mv: public media URL policy is inline data only."""
    with pytest.raises(ServiceError) as exc:
        validate_chat_request(
            {
                "model": "local-main",
                "messages": [{"role": "user", "content": [part]}],
            },
            expected_model="local-main",
            **kwargs,
        )

    assert exc.value.status_code == 422
    if exc.value.param is not None:
        assert exc.value.param == expected_param


def test_remote_audio_url_is_not_a_public_chat_content_type() -> None:
    """Public audio is input_audio raw base64, not vLLM's remote audio_url surface."""
    with pytest.raises(ServiceError) as exc:
        validate_chat_request(
            {
                "model": "local-main",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "audio_url",
                                "audio_url": {"url": "https://example.invalid/audio.wav"},
                            }
                        ],
                    }
                ],
            },
            expected_model="local-main",
            allowed_input_modalities=("text", "audio"),
            max_audio_inputs=1,
            allowed_audio_formats=("wav",),
            max_audio_bytes=25_000_000,
        )

    assert exc.value.status_code == 422
    assert "input_audio" in str(exc.value)
