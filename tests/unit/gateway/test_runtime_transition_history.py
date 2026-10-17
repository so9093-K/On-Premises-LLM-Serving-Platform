from __future__ import annotations

import asyncio
from dataclasses import replace

from ai_model_serving.services.runtime_state import RuntimeState
from ai_model_serving.settings import SecuritySettings
from .helpers import FakeGatewayClients, TestClient, create_gateway_app, settings

_DIGEST = "a" * 64


class VerifiedStartSidecar:
    def __init__(self) -> None:
        self.statuses = {"embed-ko": "exited", "embed": "running"}

    async def get_status(self):
        return dict(self.statuses)

    async def start(self, container: str, *, force: bool = False, plan_digest: str):
        assert container == "embed-ko"
        self.statuses["embed-ko"] = "running"
        if force:
            self.statuses["embed"] = "exited"
        return {
            "started": ["embed-ko"],
            "evicted": ["embed"] if force else [],
        }


class UnverifiedStartSidecar(VerifiedStartSidecar):
    async def start(self, container: str, *, force: bool = False, plan_digest: str):
        assert container == "embed-ko"
        return {"started": ["embed-ko"], "evicted": []}


def test_runtime_transition_exposes_verified_operation_and_history() -> None:
    clients = FakeGatewayClients()
    clients.runtime_controller = VerifiedStartSidecar()
    asyncio.run(clients.runtime_state.set("embedding_ko", RuntimeState.stopped))
    client = TestClient(create_gateway_app(settings(), clients))

    response = client.request(
        "PATCH",
        "/admin/runtimes/embedding_ko",
        json={"desired_state": "active", "plan_digest": _DIGEST},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_id"].startswith("rt_")
    assert body["operation_status"] == "verified"
    assert body["verification"]["converged"] is True

    history = client.get("/admin/runtimes/operations")
    assert history.status_code == 200
    assert history.json()["next_cursor"] is None
    assert len(history.json()["items"]) == 1
    item = history.json()["items"][0]
    assert item["operation_id"] == body["operation_id"]
    assert item["status"] == "verified"
    assert item["actor"] == {"auth_method": "local", "actor_id": "local_operator"}
    assert item["durable"] is False

    detail = client.get(f"/admin/runtimes/operations/{body['operation_id']}")
    assert detail.status_code == 200
    assert detail.json() == item


def test_runtime_transition_history_records_admin_actor_without_raw_key() -> None:
    token = "runtime-history-admin-key"
    base = settings()
    protected = replace(
        base,
        security=SecuritySettings(
            api_key_required=base.security.api_key_required,
            api_keys=base.security.api_keys,
            internal_service_token=base.security.internal_service_token,
            admin_api_key_required=True,
            admin_api_keys=frozenset({token}),
        ),
    )
    clients = FakeGatewayClients()
    clients.runtime_controller = VerifiedStartSidecar()
    asyncio.run(clients.runtime_state.set("embedding_ko", RuntimeState.stopped))
    client = TestClient(create_gateway_app(protected, clients))
    headers = {"Authorization": f"Bearer {token}"}

    response = client.request(
        "PATCH",
        "/admin/runtimes/embedding_ko",
        headers=headers,
        json={"desired_state": "active", "plan_digest": _DIGEST},
    )
    assert response.status_code == 200

    record = client.get(
        f"/admin/runtimes/operations/{response.json()['operation_id']}",
        headers=headers,
    ).json()
    assert record["actor"]["auth_method"] == "api_key"
    assert record["actor"]["actor_id"].startswith("admin-key:")
    assert token not in str(record)
    assert record["reviewed_plan"] is True
    assert record["plan_digest"] == "a" * 64


def test_runtime_transition_fails_closed_when_apply_cannot_be_verified() -> None:
    clients = FakeGatewayClients()
    clients.runtime_controller = UnverifiedStartSidecar()
    asyncio.run(clients.runtime_state.set("embedding_ko", RuntimeState.stopped))
    client = TestClient(create_gateway_app(settings(), clients))

    response = client.request(
        "PATCH",
        "/admin/runtimes/embedding_ko",
        json={"desired_state": "active", "plan_digest": _DIGEST},
    )

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "RUNTIME_VERIFICATION_FAILED"
    operation_id = error["details"]["operation_id"]
    assert error["details"]["verification"]["converged"] is False

    record = client.get(f"/admin/runtimes/operations/{operation_id}").json()
    assert record["status"] == "verification_failed"
    assert record["verification"]["observed_state"] == "exited"


class MissingMainStopSidecar:
    async def main_model(self):
        return {
            "runtime_state": "stopped",
            "observed_runtime": {
                "status": "unavailable",
                "container_state": "not_found",
            },
        }

    async def main_stop(self, *, plan_digest: str):
        assert plan_digest == _DIGEST
        return {"runtime_state": "stopped", "evicted": []}


def test_main_stop_verifies_absent_container_as_converged() -> None:
    # Docker 컨테이너 자체가 없는 경우 observable status는 unavailable이지만,
    # 요청 상태 stopped와 관측 상태 not_found가 함께 확인되면 종료는 완료다.
    clients = FakeGatewayClients()
    clients.runtime_controller = MissingMainStopSidecar()
    client = TestClient(create_gateway_app(settings(), clients))
    response = client.request(
        "PATCH",
        "/admin/runtimes/main",
        json={"desired_state": "stopped", "plan_digest": _DIGEST},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["operation_status"] == "verified"
    assert result["verification"]["converged"] is True
    assert result["verification"]["container_state"] == "not_found"
