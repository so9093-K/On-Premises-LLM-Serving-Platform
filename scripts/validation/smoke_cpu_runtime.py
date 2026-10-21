#!/usr/bin/env python3
"""실제 관리형 CPU 모델의 Chat/Streaming을 로컬 Gateway에서 검증한다.

CI의 설정/모의 테스트와 달리 해당 호스트에서 운영 중인 모델이 필요하다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ai_model_serving.contracts import validate_chat_response  # noqa: E402
from ai_model_serving.configuration import load_yaml_mapping  # noqa: E402
from ai_model_serving.errors import ServiceError  # noqa: E402


def _request(base_url: str, path: str, token: str, body: dict | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers)
    return urllib.request.urlopen(req, timeout=120)


def smoke(base_url: str, token: str) -> None:
    with _request(base_url, "/v1/models", token) as response:
        models = json.load(response)
    main = next((item for item in models.get("data", [])
                 if isinstance(item, dict) and item.get("id") == "local-main"), None)
    if main is None:
        raise RuntimeError("CPU model local-main is not advertised as available")
    root = Path(__file__).resolve().parents[2]
    artifact = load_yaml_mapping(root / "configs/cpu_model_artifact.yaml")["model"]
    serving = load_yaml_mapping(root / "configs/cpu_main_model_profiles.yaml")
    policy = serving["profiles"][serving["default_profile"]]["gateway_policy"]
    if (main.get("backend") != "llama-cpp"
            or main.get("upstream_model_id") != artifact["repo_id"]
            or main.get("input_modalities") != ["text"]
            or main.get("context_window") != serving["runtime"]["context_size"]
            or main.get("request_parameters", {}).get("max_tokens", {}).get("max")
            != policy["max_output_tokens"]):
        raise RuntimeError("local-main does not match the managed CPU model identity and serving limits")
    payload = {
        "model": "local-main",
        "messages": [{"role": "user", "content": "안녕하세요. 짧게 인사하세요."}],
        "temperature": 0,
        "max_tokens": 64,
    }
    with _request(base_url, "/v1/chat/completions", token, payload) as response:
        answer = json.load(response)
    answer = validate_chat_response(answer, expected_model="local-main")
    if not any(str(choice["message"].get("content") or "").strip() for choice in answer["choices"]):
        raise RuntimeError("CPU non-streaming response has no visible answer")
    with _request(base_url, "/v1/chat/completions", token, {**payload, "stream": True}) as response:
        done = False
        saw_data = False
        finished = False
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            chunk = json.loads(data)
            if not isinstance(chunk, dict) or chunk.get("error"):
                raise RuntimeError("CPU SSE stream contains an error")
            for choice in chunk.get("choices", []):
                if str(choice.get("delta", {}).get("content") or "").strip():
                    saw_data = True
                finished = finished or choice.get("finish_reason") in {"stop", "length"}
        if not (done and saw_data and finished):
            raise RuntimeError("CPU SSE stream missing visible answer, finish event or [DONE]")
    print("[cpu-smoke] PASS: local-main Chat Completions and SSE streaming")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a running CPU LLM through the Gateway.")
    parser.add_argument("--base-url", default="http://127.0.0.1:9600")
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", ""))
    args = parser.parse_args()
    try:
        smoke(args.base_url, args.api_key)
    except (OSError, RuntimeError, ValueError, ServiceError, json.JSONDecodeError, urllib.error.HTTPError) as exc:
        print(f"[cpu-smoke] FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
