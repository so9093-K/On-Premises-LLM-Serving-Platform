from __future__ import annotations

import io
import json
import logging

from .helpers import *  # noqa: F401,F403


def _response_body(*, output=None, **extra):
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1.0,
        "model": "local-main",
        "status": "completed",
        "output": output
        if output is not None
        else [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        **extra,
    }


def test_responses_non_stream_uses_responses_runtime_and_projects_internal_fields():
    clients = FakeGatewayClients()
    clients.main_llm.post_response = _response_body(metrics={"hidden": True})
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "hello"},
    )
    assert response.status_code == 200
    assert clients.main_llm.last_path == "responses"
    assert clients.main_llm.last_payload == {"model": "local-main", "input": "hello", "store": False}
    assert response.json()["output"][0]["content"][0]["text"] == "ok"
    assert "metrics" not in response.json()


def test_responses_rejects_server_side_storage_semantics():
    clients = FakeGatewayClients()
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "hello", "store": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["param"] == "store"
    assert clients.main_llm.last_path is None


def test_responses_rejects_previous_response_id_instead_of_ignoring_stateful_semantics():
    clients = FakeGatewayClients()
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "hello", "previous_response_id": "resp_old"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["param"] == "previous_response_id"
    assert clients.main_llm.last_path is None


def test_responses_reasoning_effort_is_owned_by_active_profile_policy():
    clients = FakeGatewayClients()
    clients.main_llm.post_response = _response_body()
    client = TestClient(create_gateway_app(tool_calling_settings(), clients))
    accepted = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "analyze this", "reasoning": {"effort": "medium"}},
    )
    rejected = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "analyze this", "reasoning": {"effort": "high"}},
    )
    assert accepted.status_code == 200
    assert clients.main_llm.last_payload["reasoning"] == {"effort": "medium"}
    assert rejected.status_code == 422
    assert rejected.json()["error"]["param"] == "reasoning.effort"


def test_responses_function_tools_default_parallel_calls_to_profile_policy():
    clients = FakeGatewayClients()
    clients.main_llm.post_response = _response_body(output=[{
        "id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "get_weather",
        "arguments": '{"city":"Seoul"}', "status": "completed",
    }])
    client = TestClient(create_gateway_app(tool_calling_settings(), clients))
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "local-main",
            "input": "서울 날씨를 확인해줘",
            "tools": [{
                "type": "function", "name": "get_weather", "description": "날씨 조회",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False},
            }],
            "tool_choice": "auto",
        },
    )
    assert response.status_code == 200
    assert clients.main_llm.last_payload["parallel_tool_calls"] is False
    assert response.json()["output"][0]["type"] == "function_call"

    tools = [{
        "type": "function",
        "name": "get_weather",
        "description": "날씨 조회",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }]
    for forced_choice in [
        "required",
        {"type": "function", "name": "get_weather"},
    ]:
        clients.main_llm.last_path = None
        rejected = client.post(
            "/v1/responses",
            headers=auth_headers(),
            json={
                "model": "local-main",
                "input": "서울 날씨",
                "tools": tools,
                "tool_choice": forced_choice,
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["param"] == "tool_choice"
        assert clients.main_llm.last_path is None

    clients.main_llm.post_response = _response_body()
    none = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "local-main",
            "input": "서울 날씨",
            "tools": tools,
            "tool_choice": "none",
        },
    )
    assert none.status_code == 200

    clients.main_llm.post_response = _response_body(output=[{
        "id": "fc_bad",
        "type": "function_call",
        "call_id": "call_bad",
        "name": "get_weather",
        "arguments": "{}",
        "status": "completed",
    }])
    violated_none = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={
            "model": "local-main",
            "input": "서울 날씨",
            "tools": tools,
            "tool_choice": "none",
        },
    )
    assert violated_none.status_code == 502


def test_responses_rejects_unadvertised_or_parallel_upstream_tool_calls():
    clients = FakeGatewayClients()
    client = TestClient(create_gateway_app(tool_calling_settings(), clients))
    tools = [{
        "type": "function",
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {}},
    }]

    clients.main_llm.post_response = _response_body(output=[{
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_1",
        "name": "unknown",
        "arguments": "{}",
        "status": "completed",
    }])
    unknown = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "weather", "tools": tools},
    )
    assert unknown.status_code == 502

    clients.main_llm.post_response = _response_body(output=[
        {
            "id": "fc_1", "type": "function_call", "call_id": "call_1",
            "name": "get_weather", "arguments": "{}", "status": "completed",
        },
        {
            "id": "fc_2", "type": "function_call", "call_id": "call_2",
            "name": "get_weather", "arguments": "{}", "status": "completed",
        },
    ])
    parallel = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "weather", "tools": tools},
    )
    assert parallel.status_code == 502


def test_responses_supports_self_contained_previous_output_and_tool_continuation():
    clients = FakeGatewayClients()
    clients.main_llm.post_response = _response_body()
    client = TestClient(create_gateway_app(settings(), clients))
    previous_output = [
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "Need weather."}], "content": []},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "get_weather", "arguments": '{"city":"Seoul"}', "status": "completed"},
        {"type": "function_call_output", "call_id": "call_1", "output": '{"temperature":22}'},
    ]
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": previous_output},
    )
    assert response.status_code == 200
    assert clients.main_llm.last_payload["input"] == previous_output


def test_responses_usage_is_normalized_to_existing_access_log_token_fields():
    clients = FakeGatewayClients()
    clients.main_llm.post_response = _response_body()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("ai_model_serving.gateway")
    logger.addHandler(handler)
    try:
        client = TestClient(create_gateway_app(settings(), clients))
        response = client.post(
            "/v1/responses", headers=auth_headers(), json={"model": "local-main", "input": "hello"}
        )
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 200
    records = [json.loads(line) for line in stream.getvalue().splitlines() if line.startswith("{")]
    completed = [record for record in records if record.get("event") == "http_request_completed"]
    assert completed
    record = completed[-1]
    assert record["prompt_tokens"] == 2
    assert record["completion_tokens"] == 1
    assert record["total_tokens"] == 3
    assert record["upstream_response_id"] == "resp_1"


def test_responses_stream_relays_typed_events_and_removes_runtime_internal_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("REQUEST_EVENT_LOG_DIR", str(tmp_path))
    clients = FakeGatewayClients()
    created = _response_body(output=[], metrics={"hidden": True})
    event = {"type": "response.created", "sequence_number": 0, "response": created, "internal": "hidden"}
    clients.main_llm.stream_chunks = [
        ("event: response.created\n" + "data: " + json.dumps(event) + "\n\n").encode(),
        b"data: [DONE]\n\n",
    ]
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.post(
        "/v1/responses",
        headers=auth_headers(),
        json={"model": "local-main", "input": "hello", "stream": True},
    )
    assert response.status_code == 200
    assert clients.main_llm.last_path == "responses"
    assert "event: response.created" in response.text
    assert '"type":"response.created"' in response.text
    assert '"internal"' not in response.text
    assert '"metrics"' not in response.text

    records = [json.loads(line) for line in (tmp_path / "gateway.jsonl").read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["stream_status"] == "completed"
    assert records[0]["time_to_first_chunk_ms"] >= 0
    assert records[0]["upstream_response_id"] == "resp_1"


def test_models_advertises_responses_for_main_model():
    clients = FakeGatewayClients()
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.get("/v1/models", headers=auth_headers())
    assert response.status_code == 200
    main = next(item for item in response.json()["data"] if item["id"] == "local-main")
    assert "responses" in main["capabilities"]
