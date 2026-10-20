"""수동 CPU 선택은 자동 제어 없이 기존 전환·예산·재시작 계약을 따른다."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path

import httpx
import pytest

from ai_model_serving.apps.runtime_controller import create_runtime_controller_app
from ai_model_serving.main_model.catalog import load_main_model_catalog
from ai_model_serving.main_model.control import MainModelManager
from ai_model_serving.main_model.state import MainModelStateStore
from ai_model_serving.main_model.docker_backend import DockerMainModelBackend
from tests.support.main_model import FakeBackend, _SHARED_IMAGE

ROOT = Path(__file__).resolve().parents[2]
CPU = "cpu-gguf-text"
GPU = "gemma4-e4b-it"


@pytest.mark.parametrize("fail_prepare", [False, True])
def test_manual_cpu_selection_ignores_gpu_probe_failure_and_preserves_request_contract(
    tmp_path, fail_prepare
):
    async def scenario():
        store = MainModelStateStore(tmp_path / "state.json", GPU)
        store.update(lambda s: s.update(active_profile=GPU, gate="open"))
        backend = FakeBackend(observed=GPU, fail_prepare=fail_prepare)

        class Executor:
            unavailable = True

            async def status(self, service):
                if self.unavailable:
                    raise RuntimeError("GPU observation unavailable")
                return "running" if service == "main-llm-vllm" else "exited"

        executor = Executor()
        app = create_runtime_controller_app(
            environment={
                "APP_CONFIG_ROOT": str(ROOT),
                "COMPOSE_PROJECT": "manual-test",
                "MAIN_MODEL_STATE_PATH": str(store.path),
                "VLLM_IMAGE": _SHARED_IMAGE,
                "MAIN_MODEL_RESOURCE_VARIANT": "rtx4090-24gb",
            },
            executor=executor,
            main_model_backend=backend,
        )
        manager = app.state.controller._main_model_manager
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/main-model/switch", json={"profile": CPU, "confirm_unverified": True}
            )
            assert response.status_code == 202, response.text
            operation = await manager.wait_for_operation(
                response.json()["operation_id"]
            )
            if fail_prepare:
                assert (
                    operation["status"] == "failed"
                    and operation["stage"] == "preparing"
                )
                assert manager.snapshot()["active_profile"]["id"] == GPU
                assert manager.snapshot()["gate"] == "open"
                assert backend.replaced == []
            else:
                assert operation["status"] == "completed"
                assert backend.replaced == [CPU] and backend.drain_calls == 1
                assert (
                    manager.snapshot()["active_profile"]["runtime_backend"]
                    == "llama-cpp"
                )
                assert manager.snapshot()["active_profile"]["vram_fraction"] == 0
                restarted = MainModelManager(manager.catalog, store, backend)
                await restarted.initialize()
                assert restarted.snapshot()["active_profile"]["id"] == CPU
                assert restarted.snapshot()["gate"] == "open"
                # CPU 선택은 GPU로의 자동 복귀나 관측 우회 권한을 만들지 않는다.
                blocked = await client.post(
                    "/main-model/switch",
                    json={"profile": GPU, "confirm_unverified": True},
                )
                assert blocked.status_code == 503
                assert backend.replaced == [CPU]
                executor.unavailable = False
                budget = (await client.get("/gpu-budget")).json()
                main = next(
                    p for p in budget["participants"] if p["key"] == "main-llm-vllm"
                )
                assert main["vram_fraction"] == 0
                response = await client.post(
                    "/main-model/switch",
                    json={"profile": GPU, "confirm_unverified": True},
                )
                assert response.status_code == 202, response.text
                assert (
                    await manager.wait_for_operation(response.json()["operation_id"])
                )["status"] == "completed"
                assert backend.replaced == [CPU, GPU]
        await manager.aclose()

    asyncio.run(scenario())


def test_cpu_gpu_docker_replacement_restores_device_policy_across_controller_restart(
    monkeypatch,
):
    catalog = load_main_model_catalog(
        ROOT / "configs/main_model_profiles.yaml", env={"VLLM_IMAGE": _SHARED_IMAGE}
    )
    original_requests = [{"Driver": "", "Count": -1, "Capabilities": [["gpu"]]}]
    state = [
        {
            "Name": "/manual-main",
            "Config": {
                "Image": catalog.profiles[GPU].image,
                "Cmd": list(catalog.profiles[GPU].command),
                "Labels": {},
            },
            "HostConfig": {
                "DeviceRequests": original_requests,
                "Binds": ["/cpu-cache:/models:ro"],
            },
            "NetworkSettings": {"Networks": {}},
        }
    ]
    payloads = []

    async def container(service):
        return "main-id"

    async def inspect(identifier):
        return copy.deepcopy(state[0])

    async def image(reference):
        return {
            "Config": {
                "Entrypoint": ["cpu-server"]
                if reference == catalog.profiles[CPU].image
                else ["vllm-server"],
                "Env": ["PATH=/bin"],
                "Labels": {"ai_model_serving.vllm_version": "test-version"},
            }
        }

    async def handle(request):
        if request.url.path == "/containers/create":
            payload = json.loads(request.content)
            payloads.append(payload)
            state[0] = {
                "Name": "/manual-main",
                "Config": {
                    k: v
                    for k, v in payload.items()
                    if k not in {"HostConfig", "NetworkingConfig"}
                },
                "HostConfig": payload["HostConfig"],
                "NetworkSettings": {"Networks": {}},
            }
            return httpx.Response(201, json={"Id": "new"})
        return httpx.Response(204)

    async def scenario():
        for target in (CPU, GPU):
            # 각각 새 Backend 인스턴스를 써서 메모리 내 template에 의존하지 않음을 확인한다.
            backend = DockerMainModelBackend(
                "/var/run/docker.sock", "manual", gateway_url="http://gateway:9400"
            )
            monkeypatch.setattr(backend, "_container_id", container)
            monkeypatch.setattr(backend, "_inspect", inspect)
            monkeypatch.setattr(backend, "_inspect_image", image)
            monkeypatch.setattr(
                backend,
                "_client",
                lambda: httpx.AsyncClient(
                    transport=httpx.MockTransport(handle), base_url="http://docker"
                ),
            )
            await backend.replace(catalog, catalog.profiles[target])

    asyncio.run(scenario())
    cpu, gpu = payloads
    assert cpu["HostConfig"]["DeviceRequests"] == []
    assert cpu["HostConfig"]["Memory"] == 4 * 1024**3
    assert cpu["Entrypoint"] == ["cpu-server"]
    assert gpu["HostConfig"]["DeviceRequests"] == original_requests
    assert gpu["HostConfig"]["Memory"] == 0 and gpu["HostConfig"]["MemorySwap"] == 0
    assert gpu["HostConfig"]["PidsLimit"] == 2048
    assert gpu["Entrypoint"] == ["vllm-server"]
    assert "ai_model_serving.vllm_version" not in cpu["Labels"]
    assert gpu["Labels"]["ai_model_serving.vllm_version"] == "test-version"
    assert "CUDA_VISIBLE_DEVICES=0" not in gpu["Env"]


def test_cpu_lifecycle_plan_never_evicts_gpu_reservations():
    from ai_model_serving.gpu_budget import (
        Participant,
        budget_snapshot,
        plan_activation,
    )
    from ai_model_serving.runtime_transition import plan_runtime_transition

    cpu = Participant("main", 0, active=False, evictable=False, gpu_required=False)
    gpu = Participant("other", 0.9, active=True)
    plan = plan_runtime_transition([cpu, gpu], "main", "active", ceiling=0.93)
    assert plan.admissible and plan.start == ("main",) and plan.stop == ()
    assert plan.budget_before == plan.budget_after
    assert budget_snapshot([cpu, gpu], ceiling=0.93)["used"] == 0.9
    # 일반 GPU 요구량 0은 여전히 잘못된 입력이다.
    with pytest.raises(ValueError):
        plan_activation([], "gpu", 0, ceiling=0.93)
    with pytest.raises(ValueError):
        budget_snapshot([Participant("invalid-gpu", 0, active=True)], ceiling=0.93)


def test_cpu_boot_override_really_removes_compose_gpu_devices(tmp_path, monkeypatch):
    import subprocess
    import shutil
    import yaml

    if (
        not shutil.which("docker")
        or subprocess.run(
            ["docker", "compose", "version"], capture_output=True
        ).returncode
        != 0
    ):
        pytest.skip("Docker Compose is unavailable")
    from ai_model_serving.main_model.boot import render_boot_override

    monkeypatch.delenv("MAIN_MODEL_BOOT_PROFILE", raising=False)
    env = tmp_path / "env"
    env.write_text(f"VLLM_IMAGE={_SHARED_IMAGE}\nMAIN_MODEL_BOOT_PROFILE={CPU}\n")
    profile, override = render_boot_override(
        catalog_path=ROOT / "configs/main_model_profiles.yaml",
        state_path=tmp_path / "no-state",
        env_path=env,
    )
    assert profile == CPU
    patch = tmp_path / "boot.yaml"
    patch.write_text(yaml.safe_dump(override))
    # 실행하지 않고 실제 Compose 병합으로 !reset이 GPU 장치를 제거하는지 확인한다.
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("")
    environment = {
        **os.environ,
        "PLATFORM_IMAGE": "platform:test",
        "VLLM_IMAGE": _SHARED_IMAGE,
        "COMPOSE_SERVICE_ENV_FILE": str(runtime_env),
        "GATEWAY_SERVICE_ENV_FILE": str(runtime_env),
        "RISK_SIGNAL_SERVICE_ENV_FILE": str(runtime_env),
    }
    for key in (
        "ALLOY_IMAGE",
        "CADVISOR_IMAGE",
        "DCGM_EXPORTER_IMAGE",
        "GRAFANA_IMAGE",
        "LOKI_IMAGE",
        "PROMETHEUS_IMAGE",
    ):
        environment[key] = _SHARED_IMAGE
    environment["GRAFANA_ADMIN_PASSWORD"] = "synthetic-compose-test"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "ops/compose/full-stack.private-network.yaml"),
            "-f",
            str(patch),
            "config",
            "--format",
            "json",
        ],
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    main = json.loads(result.stdout)["services"]["main-llm-vllm"]
    assert (
        main.get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
        == []
    )
    assert int(main["mem_limit"]) == 4 * 1024**3 and main["pids_limit"] == 256
    requests = json.loads(main["labels"]["ai_model_serving.gpu_device_requests"])
    assert requests[0]["Count"] == -1 and requests[0]["Capabilities"] == [["gpu"]]
    assert main["command"][main["command"].index("--n-gpu-layers") + 1] == "0"


@pytest.mark.parametrize(
    "target",
    ["linux-nvidia-dynamic", "linux-adaptive", "linux-cpu-managed", "linux-cpu-static"],
)
def test_cpu_identity_limits_and_mode_are_visible_in_public_models_and_scalar(
    tmp_path, monkeypatch, target
):
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator
    from ai_model_serving.settings import load_settings
    from ai_model_serving.apps.gateway import create_gateway_app
    from ai_model_serving.openapi_contracts import load_contract_schema
    from tests.unit.gateway.helpers import FakeGatewayClients

    monkeypatch.setenv("DEPLOYMENT_TARGET", target)
    monkeypatch.setenv("MAIN_MODEL_STATIC_PROFILE", CPU)
    config = load_settings(root=ROOT, env_file=tmp_path / "no-env")
    clients = FakeGatewayClients()
    catalog = load_main_model_catalog(
        ROOT / "configs/main_model_profiles.yaml", env={"VLLM_IMAGE": _SHARED_IMAGE}
    )
    cpu = catalog.profiles[CPU]

    class Controller:
        async def main_model(self, observed=True):
            return {
                "active_profile": cpu.public_view(),
                "gate": "open",
                "engine_policy": cpu.engine_policy(),
            }

    if target in {"linux-nvidia-dynamic", "linux-adaptive"}:
        clients.runtime_controller = Controller()
    clients.main_llm.get_response = {"data": [{"id": "local-main", "meta": {}}]}

    async def probe(path):
        return clients.main_llm.get_response

    clients.main_llm.probe_json = probe
    app = create_gateway_app(config, clients)
    response = TestClient(app).get("/v1/models")
    assert response.status_code == 200
    Draft202012Validator(
        load_contract_schema("model_list_response.schema.json")
    ).validate(response.json())
    main = next(m for m in response.json()["data"] if m["id"] == "local-main")
    assert main["backend"] == "llama-cpp"
    assert main["context_window"] == 2048
    assert main["request_parameters"]["max_tokens"]["max"] == 256
    assert main["input_modalities"] == ["text"]
    description = app.openapi()["info"]["description"]
    if target == "linux-cpu-static":
        assert "upstream_model_id" not in main
        assert "Qwen/Qwen3-0.6B-GGUF" not in description
        assert "외부 CPU Runtime 모드" in description
    else:
        assert main["upstream_model_id"] == cpu.model_id
        assert main["display_name"] == cpu.display_name
        assert "Qwen3-0.6B-GGUF" in description
    if target == "linux-nvidia-dynamic":
        assert "수동 모델 선택 모드" in description
        examples = app.openapi()["paths"]["/admin/main-model"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["examples"]
        Draft202012Validator(
            load_contract_schema("main_model_status_response.schema.json")
        ).validate(examples["cpu_serving"]["value"])
    if target == "linux-adaptive":
        assert "수동 Profile 전환은 잠겨" in description
