"""The local executor is the only non-main Docker mutation boundary."""

from __future__ import annotations

import json
import asyncio

import httpx
import pytest

from ai_model_serving.runtime_executor import DockerRuntimeExecutor


def make_executor(handler, *, allowed=frozenset({"embedding-vllm"}), project="serving"):
    class FakeDockerExecutor(DockerRuntimeExecutor):
        def _client(self):
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="http://docker"
            )
    return FakeDockerExecutor("/fake/docker.sock", project, allowed)


def docker_row(project="serving", service="embedding-vllm", *, status="running"):
    return {
        "Id": "container-1",
        "State": status,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
        },
    }


def test_executor_never_exposes_raw_ids_and_scopes_docker_mutations():
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            filters = json.loads(request.url.params["filters"])
            assert set(filters["label"]) == {
                "com.docker.compose.project=serving",
                "com.docker.compose.service=embedding-vllm",
            }
            return httpx.Response(200, json=[docker_row()])
        if request.url.path == "/containers/container-1/stop":
            return httpx.Response(204)
        if request.url.path == "/containers/container-1/start":
            return httpx.Response(204)
        raise AssertionError(f"unexpected Docker request: {request}")

    executor = make_executor(handle)
    assert asyncio.run(executor.status("embedding-vllm")) == "running"
    assert asyncio.run(executor.stop("embedding-vllm")) is True
    assert asyncio.run(executor.start("embedding-vllm")) is True
    assert calls == [
        ("GET", "/containers/json"),
        ("GET", "/containers/json"), ("POST", "/containers/container-1/stop"),
        ("GET", "/containers/json"), ("POST", "/containers/container-1/start"),
    ]


def test_executor_rejects_unauthorized_service_before_docker_access():
    def handle(_request):
        raise AssertionError("Docker must never be called for unowned service")

    executor = make_executor(handle)
    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(executor.start("unrelated-app"))
    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(executor.stop("unrelated-app"))


def test_executor_fails_closed_on_cross_project_or_ambiguous_service():
    def wrong(request):
        assert request.method == "GET"
        return httpx.Response(200, json=[docker_row(project="another-project")])

    with pytest.raises(RuntimeError):
        asyncio.run(make_executor(wrong).stop("embedding-vllm"))

    def duplicate(_request):
        return httpx.Response(200, json=[docker_row(), {**docker_row(), "Id": "container-2"}])

    with pytest.raises(RuntimeError):
        asyncio.run(make_executor(duplicate).start("embedding-vllm"))


def test_missing_container_does_not_create_or_mutate_resource():
    def handle(request):
        assert request.method == "GET"
        return httpx.Response(200, json=[])

    executor = make_executor(handle)
    assert asyncio.run(executor.status("embedding-vllm")) == "not_found"
    assert asyncio.run(executor.start("embedding-vllm")) is False
    assert asyncio.run(executor.stop("embedding-vllm")) is False


def test_executor_requires_project_scoped_authority():
    with pytest.raises(RuntimeError, match="COMPOSE_PROJECT"):
        make_executor(lambda req: httpx.Response(200, json=[]), project="")


def test_main_runtime_can_be_observed_but_not_mutated_by_secondary_executor():
    def handle(request):
        assert request.method == "GET"
        return httpx.Response(200, json=[docker_row(service="main-llm-vllm")])

    class FakeDockerExecutor(DockerRuntimeExecutor):
        def _client(self):
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handle), base_url="http://docker"
            )

    executor = FakeDockerExecutor(
        "/fake/docker.sock", "serving", frozenset({"embedding-vllm"}),
        frozenset({"main-llm-vllm"}),
    )
    assert asyncio.run(executor.status("main-llm-vllm")) == "running"
    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(executor.stop("main-llm-vllm"))
    with pytest.raises(ValueError, match="not allowlisted"):
        asyncio.run(executor.start("main-llm-vllm"))
