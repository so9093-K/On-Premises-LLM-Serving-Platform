"""/health, /ready, /v1/models의 readiness 판정을 검증한다: 필수 의존성이 죽으면
503, stopped(의도적 중지)로 표시된 optional 런타임은 그냥 ready 처리되는지 등."""

from __future__ import annotations

import pytest

from .helpers import *  # noqa: F401,F403
from ai_model_serving.services.runtime_controller_client import RuntimeControllerUnavailableError
from ai_model_serving.services.runtime_state import RuntimeState


class _ControlledMainModel:
    """Runtime Controller의 Gate 상태를 시나리오별로 바꾸는 테스트 대역."""

    def __init__(self) -> None:
        self.state = "open"

    async def main_model(self, *, observed: bool = True):
        if self.state == "unavailable":
            raise RuntimeControllerUnavailableError("connection refused")
        return {
            "public_model": "local-main",
            "active_profile": {"id": "gemma4-26b-a4b-fp8", "runtime_backend": "vllm-cuda"},
            "gate": "open" if self.state == "open" else "closed",
            "last_operation": None,
        }


def _main_dependency(body: dict) -> dict:
    return next(item for item in body["dependencies"] if item["name"] == "main_llm_vllm")


def _chat(client):
    return client.post(
        "/v1/chat/completions",
        headers=auth_headers(),
        json={"model": "local-main", "messages": [{"role": "user", "content": "hello"}]},
    )


@pytest.mark.parametrize(
    ("controller_state", "reason", "chat_code"),
    [
        ("unavailable", "MAIN_MODEL_CONTROL_UNAVAILABLE", "MAIN_MODEL_CONTROL_UNAVAILABLE"),
        ("closed", "MAIN_MODEL_GATE_CLOSED", "MAIN_MODEL_SWITCH_IN_PROGRESS"),
    ],
)
def test_controller_managed_readiness_follows_chat_admission(controller_state, reason, chat_code):
    """Runtime이 /models에 응답해도 Chat이 거부되는 동안 /ready는 준비 완료가 아니다.

    Controller 장애나 Gate 차단을 /ready가 무시하면 Load Balancer와 운영 Smoke가
    실제로는 503만 받는 Gateway로 트래픽을 보낸다. Core 생존(/health)은 모델 제어
    장애와 무관하게 유지된다.
    """
    clients = FakeGatewayClients()
    clients.runtime_controller = _ControlledMainModel()
    clients.runtime_controller.state = controller_state
    client = TestClient(create_gateway_app(settings(), clients))

    ready = client.get("/ready")
    chat = _chat(client)

    assert client.get("/health").status_code == 200
    assert ready.status_code == 503
    assert "main_llm_vllm" in ready.json()["required_not_ready_dependencies"]
    assert _main_dependency(ready.json())["message"] == reason
    assert chat.status_code == 503
    assert chat.json()["error"]["code"] == chat_code


def test_controller_gate_reason_is_not_masked_by_runtime_failure():
    """Gate가 닫힌 전환 중 Runtime도 내려가 있으면 원인은 제어 Gate로 보고한다."""
    clients = FakeGatewayClients()
    clients.runtime_controller = _ControlledMainModel()
    clients.runtime_controller.state = "closed"
    clients.main_llm.ready = False

    body = asyncio.run(_readiness(clients, settings()))

    assert _main_dependency(body)["message"] == "MAIN_MODEL_GATE_CLOSED"


def test_controller_managed_readiness_reports_runtime_failure_when_gate_is_open():
    """Gate가 열렸어도 모델 Runtime 자체가 응답하지 않으면 그 사유를 따로 보고한다."""
    clients = FakeGatewayClients()
    clients.runtime_controller = _ControlledMainModel()
    clients.main_llm.ready = False

    body = asyncio.run(_readiness(clients, settings()))

    assert body["status"] == "not_ready"
    assert _main_dependency(body)["message"].startswith("MODEL_UNAVAILABLE")


def test_controller_managed_readiness_recovers_when_gate_reopens():
    clients = FakeGatewayClients()
    clients.runtime_controller = _ControlledMainModel()
    client = TestClient(create_gateway_app(settings(), clients))

    for state in ("unavailable", "closed"):
        clients.runtime_controller.state = state
        assert client.get("/ready").status_code == 503
    clients.runtime_controller.state = "open"

    assert client.get("/ready").status_code == 200
    assert _chat(client).status_code == 200


def test_open_gate_without_active_profile_is_not_serving():
    """검증된 활성 Profile이 없는 Gate 개방은 Chat과 /ready 모두 요청 불가로 본다."""

    class GateWithoutProfile:
        async def main_model(self, *, observed: bool = True):
            return {"public_model": "local-main", "active_profile": None, "gate": "open", "last_operation": None}

    clients = FakeGatewayClients()
    clients.runtime_controller = GateWithoutProfile()
    client = TestClient(create_gateway_app(settings(), clients))

    assert client.get("/ready").status_code == 503
    assert _chat(client).status_code == 503


def test_gateway_health_and_ready():
    client = TestClient(create_gateway_app(settings(), FakeGatewayClients()))
    assert client.get("/health").json() == {"status": "ok", "service": "gateway"}
    ready = client.get("/ready").json()
    assert ready["status"] == "ready"
    assert ready["phase"] == "serving"
    assert ready["not_ready_dependencies"] == []


def test_gateway_ready_forwards_admin_token_to_risk_signal_service_readiness():
    clients = FakeGatewayClients()
    client = TestClient(create_gateway_app(admin_settings(), clients))
    response = client.get("/ready", headers={"Authorization": "Bearer admin-test-key"})
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert clients.risk_signal_service.last_path == "/ready"
    assert clients.risk_signal_service.last_headers == {"authorization": "Bearer admin-test-key"}


def test_gateway_readiness_reflects_risk_signal_service_body_status():
    clients = FakeGatewayClients()
    clients.risk_signal_service = FakeRuntimeClient(
        get_response={
            "status": "not_ready",
            "service": "risk-signal-service",
            "dependencies": [{"name": "prompt_injection_detector_runtime", "status": "not_ready"}],
        },
        endpoint=RuntimeEndpoint("risk-signal-service", "http://risk", "risk-signal-service", 1),
    )
    client = TestClient(create_gateway_app(settings(), clients))

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["phase"] == "waiting_for_dependencies"
    assert body["not_ready_dependencies"] == ["risk-signal-service"]
    assert {item["name"]: item["status"] for item in body["dependencies"]}["risk-signal-service"] == "not_ready"
    risk_dependency = next(item for item in body["dependencies"] if item["name"] == "risk-signal-service")
    assert risk_dependency["endpoint"] == "http://risk/ready"
    assert "prompt_injection_detector_runtime" in risk_dependency["message"]


def test_gateway_readiness_503_when_embedding_ko_vllm_down():
    clients = FakeGatewayClients()
    embedding_ko = FakeRuntimeClient(
        ready=False,
        get_response={"error": "model not loaded"},
        endpoint=RuntimeEndpoint("local-embed-ko", "http://embed-ko/v1", "local-embed-ko", 1),
    )
    clients.embedding_clients["local-embed-ko"] = embedding_ko
    clients.runtime_clients_by_service_key["embedding_ko"] = embedding_ko
    clients.runtimes["embedding_ko"] = embedding_ko
    client = TestClient(create_gateway_app(settings(), clients))

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "embedding_ko_vllm" in body["not_ready_dependencies"]
    assert "embedding_ko_vllm" in body["required_not_ready_dependencies"]
    assert "embedding_ko_vllm" not in body["optional_not_ready_dependencies"]


def test_gateway_readiness_treats_stopped_runtime_as_optional():
    clients = FakeGatewayClients()
    embedding_ko = FakeRuntimeClient(
        ready=False,
        get_response={"error": "model not loaded"},
        endpoint=RuntimeEndpoint("local-embed-ko", "http://embed-ko/v1", "local-embed-ko", 1),
    )
    clients.embedding_clients["local-embed-ko"] = embedding_ko
    clients.runtime_clients_by_service_key["embedding_ko"] = embedding_ko
    clients.runtimes["embedding_ko"] = embedding_ko
    asyncio.run(clients.runtime_state.set("embedding_ko", RuntimeState.stopped))
    client = TestClient(create_gateway_app(settings(), clients))

    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert "embedding_ko_vllm" in body["not_ready_dependencies"]
    assert "embedding_ko_vllm" in body["optional_not_ready_dependencies"]
    assert "embedding_ko_vllm" not in body["required_not_ready_dependencies"]


def test_gateway_readiness_builds_embedding_probes_from_profiles():
    cfg = settings()
    clients = FakeGatewayClients()

    body = asyncio.run(_readiness(clients, cfg))

    dependency_names = {item["name"] for item in body["dependencies"]}
    assert {"embedding_vllm", "embedding_ko_vllm"}.issubset(dependency_names)


def test_gateway_readiness_picks_up_new_embedding_route_without_code_change():
    """embedding route 추가는 설정 변경으로 끝나야 한다 -- gateway 코드는 그대로다."""
    base = settings()
    extra_endpoint = RuntimeEndpoint("local-embed-extra", "http://embed-extra/v1", "local-embed-extra", 1)
    extra_profile = EmbeddingProfile(
        model="local-embed-extra",
        service_key="embedding_extra",
        default_dimensions=384,
        retrieval_enabled=True,
    )
    cfg = _settings_with_embedding_profiles(
        embedding_profiles={**base.embedding_profiles, "local-embed-extra": extra_profile},
        runtime_endpoints={"embedding_extra": extra_endpoint},
        # 새 embedding route를 붙이는 일은 runtime_topology.yaml에 service_id를
        # 선언하는 것까지다. /ready는 그 이름을 그대로 쓴다.
        runtime_service_ids={"embedding_extra": "embedding_extra_vllm"},
    )
    clients = FakeGatewayClients()
    clients.runtime_clients_by_service_key["embedding_extra"] = FakeRuntimeClient(
        endpoint=extra_endpoint,
    )

    body = asyncio.run(_readiness(clients, cfg))

    dependency_names = {item["name"] for item in body["dependencies"]}
    assert "embedding_extra_vllm" in dependency_names


def test_collect_readiness_response_matches_schema():
    schema = json.loads(Path("specs/schemas/readiness_response.schema.json").read_text())
    validator = Draft202012Validator(schema)

    required_client = FakeRuntimeClient(endpoint=RuntimeEndpoint("req", "http://req/v1", "req", 1))
    optional_client = FakeRuntimeClient(
        ready=False,
        get_response={"error": "not ready"},
        endpoint=RuntimeEndpoint("opt", "http://opt/v1", "opt", 1),
    )
    probes = [
        DependencyProbe("required_dep", required_client, "models", required=True),
        DependencyProbe("optional_dep", optional_client, "models", required=False),
    ]

    body = asyncio.run(collect_readiness(service="gateway", probes=probes))

    validator.validate(body)
    assert body["status"] == "ready"
    assert body["required_not_ready_dependencies"] == []
    assert body["optional_not_ready_dependencies"] == ["optional_dep"]
    assert body["not_ready_dependencies"] == ["optional_dep"]


def test_explicitly_stopped_prompt_detector_does_not_block_cpu_core_readiness():
    clients = FakeGatewayClients()
    clients.risk_signal_service = FakeRuntimeClient({"status": "ok", "service": "risk-signal-service"})
    asyncio.run(clients.runtime_state.set("prompt_injection_detector", RuntimeState.stopped))
    body = asyncio.run(_readiness(clients, settings()))
    assert body["status"] == "ready"
    assert clients.risk_signal_service.last_path == "/health"
    # 중지 의도가 없거나 실제 서비스 장애이면 기존 장애 계약을 유지한다.
    clients.risk_signal_service.ready = False
    body = asyncio.run(_readiness(clients, settings()))
    assert body["status"] == "not_ready"
