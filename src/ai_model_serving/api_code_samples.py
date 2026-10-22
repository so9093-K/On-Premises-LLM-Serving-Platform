from __future__ import annotations

import json
import os
import pprint
from typing import Any

from .api_examples import GATEWAY_CHAT_REQUEST_EXAMPLES, GATEWAY_RESPONSES_REQUEST_EXAMPLES
from .port_namespace import load_port_namespace


def default_gateway_url() -> str:
    """API 문서 예제의 기본 주소. 배포 포트 대역의 Gateway Host 포트를 따른다."""
    port = load_port_namespace().host_port("gateway", os.environ)
    return f"http://127.0.0.1:{port}"


def _python_openai_sample(*, resource: str, payload: dict[str, Any], result_expression: str) -> str:
    request_literal = pprint.pformat(payload, sort_dicts=False, width=100)
    return (
        "import os\n"
        "from openai import OpenAI\n\n"
        "gateway_url = os.environ.get(\"GATEWAY_URL\", \"%s\").rstrip(\"/\")\n"
        "client = OpenAI(\n"
        "    api_key=os.environ.get(\"API_KEY\", \"local-open\"),\n"
        "    base_url=f\"{gateway_url}/v1\",\n"
        ")\n\n"
        "response = client.%s.create(**%s)\n"
        "print(%s)\n"
    ) % (default_gateway_url(), resource, request_literal, result_expression)


def _javascript_openai_sample(*, resource: str, payload: dict[str, Any], result_expression: str) -> str:
    request_literal = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        'import OpenAI from "openai";\n\n'
        'const configuredGatewayUrl = process.env.GATEWAY_URL ?? "%s";\n'
        'const gatewayUrl = configuredGatewayUrl.endsWith("/")\n'
        '  ? configuredGatewayUrl.slice(0, -1)\n'
        '  : configuredGatewayUrl;\n'
        "const client = new OpenAI({\n"
        '  apiKey: process.env.API_KEY ?? "local-open",\n'
        "  baseURL: `${gatewayUrl}/v1`,\n"
        "});\n\n"
        "const response = await client.%s.create(%s);\n"
        "console.log(%s);\n"
    ) % (default_gateway_url(), resource, request_literal, result_expression)


def _openai_sdk_samples(
    *,
    resource: str,
    example: dict[str, Any],
    python_result: str,
    javascript_result: str,
) -> list[dict[str, str]]:
    payload = example["value"]
    if not isinstance(payload, dict):
        raise TypeError("OpenAI SDK code samples require an object request example")
    return [
        {
            "lang": "Python",
            "label": "OpenAI Python SDK",
            "source": _python_openai_sample(
                resource=resource,
                payload=payload,
                result_expression=python_result,
            ),
        },
        {
            "lang": "JavaScript",
            "label": "OpenAI JavaScript SDK",
            "source": _javascript_openai_sample(
                resource=resource,
                payload=payload,
                result_expression=javascript_result,
            ),
        },
    ]


GATEWAY_CHAT_CODE_SAMPLES = _openai_sdk_samples(
    resource="chat.completions",
    example=GATEWAY_CHAT_REQUEST_EXAMPLES["basic"],
    python_result="response.choices[0].message.content",
    javascript_result="response.choices[0].message.content",
)

GATEWAY_RESPONSES_CODE_SAMPLES = _openai_sdk_samples(
    resource="responses",
    example=GATEWAY_RESPONSES_REQUEST_EXAMPLES["basic"],
    python_result="response.output_text",
    javascript_result="response.output_text",
)
