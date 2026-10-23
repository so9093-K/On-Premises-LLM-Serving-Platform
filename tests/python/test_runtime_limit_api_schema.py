"""관리형 서버 한도와 공개 API 문서의 동적 상한 계약."""

from ai_model_serving.openapi_contracts import (
    load_contract_schema,
    narrow_chat_request_schema,
    narrow_responses_request_schema,
)


def test_controller_managed_chat_schema_does_not_publish_stale_output_ceiling():
    policies = [{"max_output_tokens": 13000, "request_limits": {"max_model_len": 20000}}]
    schema = narrow_chat_request_schema(
        load_contract_schema("chat_completion_request.schema.json"),
        policies,
        allows_runtime_limit_edit=True,
    )
    assert "maximum" not in schema["properties"]["max_tokens"]
    assert "maximum" not in schema["properties"]["max_completion_tokens"]
    assert schema["properties"]["max_tokens"]["minimum"] == 1


def test_static_chat_schema_keeps_declared_output_ceiling():
    policies = [{"max_output_tokens": 4096, "request_limits": {"max_model_len": 8192}}]
    schema = narrow_chat_request_schema(
        load_contract_schema("chat_completion_request.schema.json"), policies,
    )
    assert schema["properties"]["max_tokens"]["maximum"] == 4096
    assert schema["properties"]["max_completion_tokens"]["maximum"] == 4096


def test_controller_managed_responses_schema_does_not_publish_stale_output_ceiling():
    policies = [{"max_output_tokens": 13000}]
    schema = narrow_responses_request_schema(
        load_contract_schema("responses_request.schema.json"),
        policies,
        allows_runtime_limit_edit=True,
    )
    assert "maximum" not in schema["properties"]["max_output_tokens"]
