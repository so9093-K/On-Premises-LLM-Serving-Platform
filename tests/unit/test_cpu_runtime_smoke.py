"""CPU 검증이 같은 별칭의 GPU 또는 다른 모델을 통과시키지 않는다."""

import io
import json

import pytest

from scripts.validation import smoke_cpu_runtime as cpu_smoke


def model():
    return {
        "id": "local-main",
        "backend": "llama-cpp",
        "upstream_model_id": "Qwen/Qwen3-0.6B-GGUF",
        "input_modalities": ["text"],
        "context_window": 2048,
        "request_parameters": {"max_tokens": {"max": 256}},
    }


@pytest.mark.parametrize("change", [
    {"backend": "vllm-cuda"},
    {"upstream_model_id": "another/gguf"},
    {"input_modalities": ["text", "image"]},
    {"context_window": 4096},
    {"request_parameters": {"max_tokens": {"max": 512}}},
])
def test_cpu_smoke_rejects_wrong_runtime_before_inference(monkeypatch, change):
    calls = []

    def request(base_url, path, token, body=None):
        calls.append(path)
        return io.BytesIO(json.dumps({"data": [{**model(), **change}]}).encode())

    monkeypatch.setattr(cpu_smoke, "_request", request)
    with pytest.raises(RuntimeError, match="managed CPU model"):
        cpu_smoke.smoke("http://gateway", "")
    assert calls == ["/v1/models"]


def test_cpu_smoke_checks_chat_and_stream_after_identity(monkeypatch, capsys):
    answer = {
        "id": "chat-test", "object": "chat.completion", "created": 1,
        "model": "local-main",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "안녕하세요"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
    }
    chunk = {"choices": [{"delta": {"content": "안녕하세요"}, "finish_reason": "stop"}]}
    replies = iter([
        json.dumps({"data": [model()]}).encode(),
        json.dumps(answer).encode(),
        ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode(),
    ])
    calls = []

    def request(base_url, path, token, body=None):
        calls.append((path, body))
        return io.BytesIO(next(replies))

    monkeypatch.setattr(cpu_smoke, "_request", request)
    cpu_smoke.smoke("http://gateway", "")
    assert "PASS" in capsys.readouterr().out
    assert len(calls) == 3
    assert calls[1][1].get("stream", False) is False
    assert calls[2][1]["stream"] is True
