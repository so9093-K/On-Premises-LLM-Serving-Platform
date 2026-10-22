from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from typing import Any

import httpx

from ..contracts.chat_response import validate_chat_response
from ..docker_scope import compose_container_filter, scoped_container_id
from ..errors import ServiceError
from ..host_resource_probe import valid_gpu_uuid
from ..project_paths import resolve_project_root
from .cpu import prepare_cpu_model
from .catalog import MainModelCatalog, MainModelProfile
from ..media_samples import TINY_JPEG_1X1_B64, TINY_M4A_AAC_B64, TINY_MP4_VIDEO_B64
from .cache import default_hf_hub_cache_dir, prepare_model_snapshot

_IMAGE_CANARY_JPEG_B64 = TINY_JPEG_1X1_B64
_AUDIO_CANARY_M4A_B64 = TINY_M4A_AAC_B64
_VIDEO_CANARY_MP4_B64 = TINY_MP4_VIDEO_B64
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# Docker Engine API HTTP 호출 타임아웃(초 단위). 이 값들은 로컬 docker 소켓에 대한
# 요청만을 제한하며, 모델 lifecycle(drain/stop/startup)은 catalog.runtime에 있는
# 프로필 자체의 타임아웃으로 관리된다.
_DOCKER_INSPECT_TIMEOUT = 5          # 가벼운 list/inspect GET
_HEALTH_URL_PORT = re.compile(r"(https?://(?:127\.0\.0\.1|localhost)):\d+/health")
_DOCKER_API_TIMEOUT = 30             # 컨테이너 create / start
_DOCKER_DELETE_TIMEOUT = 10          # 컨테이너 delete
_DOCKER_STOP_TIMEOUT_BUFFER = 10     # stop HTTP 타임아웃 = docker stop grace + 이 값
_DRAIN_POLL_CLIENT_TIMEOUT = 3       # drain-status poll 요청 1회당
_DRAIN_POLL_INTERVAL_SECONDS = 0.25  # drain-status poll 사이 간격
_HEALTH_POLL_INTERVAL_SECONDS = 3    # 컨테이너 health poll 사이 간격
_RUNTIME_HTTP_TIMEOUT = 30           # vLLM 런타임으로의 HTTP 요청(/v1/models, canary)


def _validate_inference_canary(payload: object, *, expected_model: str, kind: str) -> None:
    """전환 canary가 실제 Gateway 응답 계약의 최소 형태를 충족하는지 확인한다."""
    try:
        body = validate_chat_response(payload, expected_model=expected_model)
    except ServiceError as exc:
        raise RuntimeError(f"main runtime {kind} canary returned an invalid completion: {exc.message}") from exc
    choices = body["choices"]
    content = choices[0]["message"].get("content")
    if not isinstance(content, str) or not content:
        raise RuntimeError(f"main runtime {kind} canary returned no content")

class DockerMainModelBackend:
    """허용 목록에 있는 Compose main-model 컨테이너만 재생성한다.

    호출자가 image, command, 컨테이너명, project명, mount, network를 지정할 수 없게
    하며, 이 값들은 profile catalog 또는 검사한 허용 Compose 컨테이너에서만 가져온다.
    """

    def __init__(
        self,
        docker_socket: str,
        compose_project: str = "",
        *,
        gateway_url: str,
        internal_token: str = "",
        cache_dir: str | None = None,
        config_root: Path | None = None,
        cpu_cache_dir: Path | None = None,
    ) -> None:
        self.docker_socket = docker_socket
        self.compose_project = compose_project
        self.gateway_url = gateway_url.rstrip("/")
        self.internal_headers = (
            {"Authorization": f"Bearer {internal_token}"} if internal_token else {}
        )
        # Hugging Face는 저장소를 *hub* 캐시(HF_HOME/hub) 아래에 저장하며, vLLM도
        # 이 위치에서 조회한다. snapshot_download(cache_dir=X)는 X/models--...에
        # 기록하므로, cache_dir은 HF_HOME이 아니라 반드시 hub 디렉터리여야 한다.
        # 그렇지 않으면 준비된 snapshot이 런타임이 resolve하는 위치보다 한 단계 위에
        # 놓이게 된다.
        self.cache_dir = Path(cache_dir) if cache_dir else default_hf_hub_cache_dir()
        self.config_root = config_root or resolve_project_root()
        self.cpu_cache_dir = cpu_cache_dir or self.config_root / ".runtime/cpu-models"
        self._template: dict[str, Any] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=self.docker_socket),
            base_url="http://docker",
        )

    def _filters(self, service: str) -> str:
        return compose_container_filter(self.compose_project, service)

    async def _container_ids(self, service: str) -> list[str]:
        async with self._client() as client:
            response = await client.get(
                "/containers/json",
                params={"all": "true", "filters": self._filters(service)},
                timeout=_DOCKER_INSPECT_TIMEOUT,
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise RuntimeError("Docker container listing must be a list")
            return [
                scoped_container_id(
                    row,
                    project=self.compose_project,
                    service=service,
                )
                for row in rows
            ]

    async def _container_id(self, service: str) -> str | None:
        ids = await self._container_ids(service)
        if len(ids) > 1:
            raise RuntimeError(
                f"multiple containers found for allowlisted service {service} "
                f"in Compose project {self.compose_project!r}: {len(ids)}"
            )
        return ids[0] if ids else None

    async def _inspect(self, container_id: str) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(f"/containers/{container_id}/json", timeout=_DOCKER_INSPECT_TIMEOUT)
            response.raise_for_status()
            return response.json()

    async def _inspect_image(self, image_id: str) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(f"/images/{image_id}/json", timeout=_DOCKER_INSPECT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Docker image inspect must be a mapping")
            return payload

    @staticmethod
    def _distribution_image_digest(
        image_ref: str | None,
        image_inspected: dict[str, Any],
    ) -> str | None:
        """실행 image의 registry/distribution digest를 반환하고 추측하지 않는다."""
        if image_ref and "@" in image_ref:
            digest = image_ref.rsplit("@", 1)[1]
            if _IMAGE_DIGEST.fullmatch(digest):
                return digest

        raw_repo_digests = image_inspected.get("RepoDigests")
        if not isinstance(raw_repo_digests, list):
            return None

        repo_digests: list[tuple[str, str]] = []
        for value in raw_repo_digests:
            if not isinstance(value, str) or "@" not in value:
                continue
            repository, digest = value.rsplit("@", 1)
            if _IMAGE_DIGEST.fullmatch(digest):
                repo_digests.append((repository, digest))
        if not repo_digests:
            return None

        if image_ref:
            repository = image_ref.rsplit("@", 1)[0]
            last_segment = repository.rsplit("/", 1)[-1]
            if ":" in last_segment:
                repository = repository.rsplit(":", 1)[0]
            matched = {digest for repo, digest in repo_digests if repo == repository}
            if len(matched) == 1:
                return next(iter(matched))

        candidates = {digest for _, digest in repo_digests}
        return next(iter(candidates)) if len(candidates) == 1 else None

    async def observed_started_at(self, catalog: MainModelCatalog) -> str | None:
        """실행 중인 컨테이너의 Docker ``State.StartedAt``을 반환하고 없으면 ``None``을 반환한다.

        관리자 API를 거치지 않은 컨테이너 재시작을 감지하고, 활성 Profile의 실제
        health·모델 식별·입력 capability를 다시 검증하는 데 사용한다.
        """
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is None:
            return None
        inspected = await self._inspect(container_id)
        state = inspected.get("State") or {}
        # 종료된 컨테이너에도 이전 StartedAt이 남는다.
        # 이를 살아 있는 검증된 인스턴스로 취급하면 모델 프로세스가 종료됐는데도
        # Gateway의 요청 Gate가 열린 상태로 남을 수 있다.
        if state.get("Status") != "running":
            return None
        started_at = state.get("StartedAt")
        return str(started_at) if started_at else None

    @staticmethod
    def _profile_from_inspected(
        catalog: MainModelCatalog, inspected: dict[str, Any]
    ) -> str | None:
        """실행 중인 컨테이너가 일치하는 Catalog Profile의 실행 계약을 찾는다.

        Profile의 실행 계약은 Catalog가 확정한 Runtime 이미지와 최종 argv다. argv에는
        모델·Revision 신원과 함께 Resource Variant·Host GPU 비율 override를 적용한 뒤의
        Context·Batch·Sequence·GPU 메모리 예약 인자가 들어 있다. Compose boot override와
        Controller의 재생성은 모두 이 argv를 그대로 ``Cmd``로 쓰므로, 같은 모델을 다른
        자원 정책으로 실행한 컨테이너는 어떤 Profile로도 인정하지 않는다. 그래야 이전
        Canary 결과가 다른 실행 정책의 인스턴스로 승계되지 않는다. Docker가 부여하는
        메타데이터·Label·환경변수는 실행 계약이 아니므로 비교하지 않는다.
        """
        config = inspected.get("Config", {})
        command = list(config.get("Cmd") or [])
        image = config.get("Image")
        return next(
            (
                profile.profile_id
                for profile in catalog.profiles.values()
                if image == profile.image and command == list(profile.command)
            ),
            None,
        )

    async def observe_runtime(self, catalog: MainModelCatalog) -> dict[str, Any]:
        """Docker inspect 한 번으로 실제 main runtime 상태를 읽는다."""
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is None:
            return {
                "status": "unavailable",
                "container_state": "not_found",
                "health": None,
                "profile_id": None,
                "error": None,
            }
        inspected = await self._inspect(container_id)
        state = inspected.get("State", {})
        config = inspected.get("Config", {})
        labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
        image_ref_value = config.get("Image")
        image_id_value = inspected.get("Image")
        vllm_version_value = labels.get("ai_model_serving.vllm_version")
        image_ref = str(image_ref_value) if image_ref_value else None
        image_id = str(image_id_value) if image_id_value else None
        image_inspected: dict[str, Any] = {}
        if image_id and not (
            image_ref
            and "@" in image_ref
            and _IMAGE_DIGEST.fullmatch(image_ref.rsplit("@", 1)[1])
        ):
            image_inspected = await self._inspect_image(image_id)
        image_digest = self._distribution_image_digest(image_ref, image_inspected)
        vllm_version = str(vllm_version_value) if vllm_version_value else None
        container_state = str(state.get("Status") or "unknown")
        health_value = state.get("Health", {}).get("Status")
        health = str(health_value) if health_value is not None else None
        if container_state != "running":
            status = "stopped"
        elif health == "healthy":
            status = "ready"
        elif health == "starting":
            status = "starting"
        elif health == "unhealthy":
            status = "unavailable"
        else:
            status = "unknown"
        profile_id = self._profile_from_inspected(catalog, inspected)
        backend = catalog.profiles[profile_id].runtime_backend if profile_id else "vllm-cuda"
        device_uuid = None
        if catalog.runtime.get("adaptive"):
            requests = inspected.get("HostConfig", {}).get("DeviceRequests") or []
            if len(requests) == 1:
                ids = requests[0].get("DeviceIDs") or []
                if len(ids) == 1:
                    if valid_gpu_uuid(ids[0]):
                        device_uuid = ids[0]
        return {
            "status": status,
            "container_state": container_state,
            "health": health,
            "profile_id": profile_id,
            "image_ref": image_ref,
            "image_id": image_id,
            "image_digest": image_digest,
            "runtime_engine": {"name": "llama-cpp" if backend == "llama-cpp" else "vllm",
                               "version": None if backend == "llama-cpp" else vllm_version},
            **({"gpu_device_uuid": device_uuid} if catalog.runtime.get("adaptive") else {}),
            "error": None,
        }

    async def stop(self, catalog: MainModelCatalog) -> None:
        """컨테이너는 유지한 채 main runtime을 중지해 VRAM을 회수한다."""
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is None:
            return
        grace = int(catalog.runtime.get("stop_timeout_seconds", 30))
        async with self._client() as client:
            stopped = await client.post(
                f"/containers/{container_id}/stop",
                params={"t": grace},
                timeout=grace + _DOCKER_STOP_TIMEOUT_BUFFER,
            )
            if stopped.status_code not in (204, 304):
                stopped.raise_for_status()

    async def start(self, catalog: MainModelCatalog) -> None:
        """기존에 중지된 main runtime 컨테이너를 저장된 프로필로 시작한다."""
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is None:
            raise RuntimeError("main runtime container not found to start")
        async with self._client() as client:
            started = await client.post(f"/containers/{container_id}/start", timeout=_DOCKER_API_TIMEOUT)
            if started.status_code not in (204, 304):
                started.raise_for_status()

    async def observed_profile(self, catalog: MainModelCatalog) -> str | None:
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is None:
            return None
        inspected = await self._inspect(container_id)
        return self._profile_from_inspected(catalog, inspected)

    async def prepare(
        self, catalog: MainModelCatalog, profile: MainModelProfile
    ) -> None:
        if profile.runtime_backend == "llama-cpp":
            container_id = await self._container_id(str(catalog.runtime["compose_service"]))
            if container_id:
                inspected = await self._inspect(container_id)
                host = inspected.get("HostConfig", {})
                mounted = any(isinstance(b, str) and len(b.split(":")) >= 2 and b.split(":")[1] == "/models" for b in host.get("Binds") or []) or any(m.get("Target") == "/models" for m in host.get("Mounts") or [])
                if not mounted:
                    raise RuntimeError("CPU_MODEL_MOUNT_UNAVAILABLE: run make up to update the Main container")
            await asyncio.to_thread(prepare_cpu_model, config_root=self.config_root, output_root=self.cpu_cache_dir)
            # CPU image 다운로드 실패도 기존 GPU의 Gate·컨테이너를 유지한다.
            try:
                await self._inspect_image(profile.image)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                async with self._client() as client:
                    response = await client.post("/images/create", params={"fromImage": profile.image}, timeout=600)
                    response.raise_for_status()
                    for line in response.text.splitlines():
                        if line.strip() and json.loads(line).get("error"):
                            raise RuntimeError("CPU image preparation failed")
                await self._inspect_image(profile.image)
            return
        await asyncio.to_thread(
            prepare_model_snapshot,
            model_id=profile.model_id,
            revision=profile.revision,
            cache_dir=self.cache_dir,
        )

    @staticmethod
    def _creation_template(inspected: dict[str, Any]) -> dict[str, Any]:
        config = inspected["Config"]
        host = inspected["HostConfig"]
        networks = inspected.get("NetworkSettings", {}).get("Networks", {})
        endpoints: dict[str, Any] = {}
        for name, value in networks.items():
            endpoints[name] = {
                key: copy.deepcopy(value[key])
                for key in ("Aliases", "Links", "IPAMConfig", "DriverOpts", "GwPriority")
                if value.get(key) is not None
            }
        host_keys = (
            "Binds",
            "Mounts",
            "NetworkMode",
            "RestartPolicy",
            "AutoRemove",
            "VolumeDriver",
            "VolumesFrom",
            "CapAdd",
            "CapDrop",
            "CgroupnsMode",
            "Dns",
            "DnsOptions",
            "DnsSearch",
            "ExtraHosts",
            "GroupAdd",
            "IpcMode",
            "PidMode",
            "Privileged",
            "ReadonlyRootfs",
            "SecurityOpt",
            "ShmSize",
            "Sysctls",
            "Ulimits",
            "DeviceRequests",
            "PortBindings",
        )
        host_config = {key: copy.deepcopy(host[key]) for key in host_keys if host.get(key) is not None}
        return {
            "name": inspected["Name"].lstrip("/"),
            "config": {
                key: copy.deepcopy(config[key])
                for key in (
                    "Entrypoint",
                    "Env",
                    "WorkingDir",
                    "User",
                    "Labels",
                    "Healthcheck",
                    "ExposedPorts",
                    "StopSignal",
                    "StopTimeout",
                    "Tty",
                    "OpenStdin",
                )
                if config.get(key) is not None
            },
            "host_config": host_config,
            "networking_config": {"EndpointsConfig": endpoints},
        }

    async def wait_for_drain(self, timeout_seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_in_flight: int | None = None
        async with httpx.AsyncClient(timeout=_DRAIN_POLL_CLIENT_TIMEOUT) as client:
            while asyncio.get_running_loop().time() < deadline:
                response = await client.get(
                    f"{self.gateway_url}/internal/main-model/drain-status",
                    headers=self.internal_headers,
                )
                response.raise_for_status()
                last_in_flight = int(response.json().get("in_flight", -1))
                if last_in_flight == 0:
                    return
                await asyncio.sleep(_DRAIN_POLL_INTERVAL_SECONDS)
        raise RuntimeError(
            f"main-model request drain timed out with in_flight={last_in_flight}"
        )

    @staticmethod
    def _saved_gpu_device_requests(labels: dict[str, str]) -> list[dict[str, Any]]:
        try:
            requests = json.loads(labels.get("ai_model_serving.gpu_device_requests", "[]"))
            if not isinstance(requests, list) or not requests or any(
                not isinstance(request, dict)
                or request.get("Driver", "") not in {"", "nvidia"}
                or not any(isinstance(capabilities, list) and "gpu" in capabilities for capabilities in request.get("Capabilities", []))
                for request in requests
            ):
                raise ValueError("invalid saved GPU device requests")
            return requests
        except (ValueError, TypeError) as exc:
            raise RuntimeError("GPU_DEVICE_CONFIGURATION_UNAVAILABLE") from exc

    async def replace(self, catalog: MainModelCatalog, profile: MainModelProfile) -> None:
        service = str(catalog.runtime["compose_service"])
        container_id = await self._container_id(service)
        if container_id is not None:
            inspected = await self._inspect(container_id)
            self._template = self._creation_template(inspected)
        if self._template is None:
            raise RuntimeError("main runtime container template is unavailable")
        labels = self._template["config"].setdefault("Labels", {})
        source_cpu = labels.get("ai_model_serving.runtime_backend") == "llama-cpp"
        source_profile = self._profile_from_inspected(catalog, inspected) if container_id is not None else None
        if source_profile:
            source_cpu = catalog.profiles[source_profile].runtime_backend == "llama-cpp"
        engine_change = getattr(self, "gpu_uuid", None) is not None or catalog.runtime.get("adaptive") or source_cpu or profile.runtime_backend == "llama-cpp"
        image_config = None
        if engine_change:
            # 이미지·장치 설정 오류는 기존 컨테이너 해체 전에 확인한다.
            image_config = (await self._inspect_image(profile.image))["Config"]
            if catalog.runtime.get("adaptive") and profile.runtime_backend != "llama-cpp" and getattr(self, "gpu_uuid", None) is None:
                raise RuntimeError("GPU device admission is required before replacement")
            previous_requests = self._template["host_config"].get("DeviceRequests") or []
            if previous_requests:
                labels["ai_model_serving.gpu_device_requests"] = json.dumps(previous_requests)
            if profile.runtime_backend != "llama-cpp" and not catalog.runtime.get("adaptive"):
                self._saved_gpu_device_requests(labels)
        if container_id is not None:
            grace = int(catalog.runtime.get("stop_timeout_seconds", 30))
            async with self._client() as client:
                stopped = await client.post(
                    f"/containers/{container_id}/stop",
                    params={"t": grace},
                    timeout=grace + _DOCKER_STOP_TIMEOUT_BUFFER,
                )
                if stopped.status_code not in (204, 304):
                    stopped.raise_for_status()
                removed = await client.delete(f"/containers/{container_id}", timeout=_DOCKER_DELETE_TIMEOUT)
                if removed.status_code != 204:
                    removed.raise_for_status()
        if self._template is None:
            raise RuntimeError("main runtime container template is unavailable")

        payload = copy.deepcopy(self._template["config"])
        # 공유 기본 이미지 대신 active profile의 resolve된 이미지를 사용한다(프로필이
        # 자체 런타임을 고정할 수 있다, 예: audio 지원 빌드). loader는 profile.image가
        # digest로 고정되어 있고 비어있지 않음을 보장한다.
        payload["Image"] = str(profile.image)
        payload["Cmd"] = list(profile.command)
        # 포트 대역이 바뀐 뒤 같은 엔진으로 재생성해도 이전 컨테이너의 포트를 승계하지 않는다.
        port = int(catalog.runtime["container_port"])
        payload["ExposedPorts"] = {f"{port}/tcp": {}}
        if isinstance(payload.get("Healthcheck"), dict):
            payload["Healthcheck"]["Test"] = [
                _HEALTH_URL_PORT.sub(rf"\g<1>:{port}/health", item) if isinstance(item, str) else item
                for item in payload["Healthcheck"].get("Test") or []
            ]
        payload["HostConfig"] = copy.deepcopy(self._template["host_config"])
        payload["NetworkingConfig"] = copy.deepcopy(self._template["networking_config"])
        if engine_change:
            # 서로 다른 엔진의 이미지 기본값을 이전 컨테이너에서 상속하지 않는다.
            config = image_config
            for key in ("Entrypoint", "User", "WorkingDir"):
                payload[key] = copy.deepcopy(config.get(key) or ("" if key != "Entrypoint" else []))
            payload["Env"] = list(config.get("Env") or []) + [
                "HF_HOME=/root/.cache/huggingface", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
            ]
            cpu = profile.runtime_backend == "llama-cpp"
            host = payload["HostConfig"]
            # 엔진 버전은 이전 컨테이너가 아니라 대상 image의 근거를 따른다.
            payload["Labels"].pop("ai_model_serving.vllm_version", None)
            image_version = (config.get("Labels") or {}).get("ai_model_serving.vllm_version")
            if not cpu and image_version:
                payload["Labels"]["ai_model_serving.vllm_version"] = image_version
            payload["Labels"]["ai_model_serving.runtime_backend"] = profile.runtime_backend
            if cpu:
                host["DeviceRequests"] = []
            elif catalog.runtime.get("adaptive") or getattr(self, "gpu_uuid", None) is not None:
                host["DeviceRequests"] = [{"Driver": "nvidia", "DeviceIDs": [str(self.gpu_uuid)], "Capabilities": [["gpu"]]}]
            else:
                host["DeviceRequests"] = self._saved_gpu_device_requests(payload["Labels"])
            host["Memory"] = int(catalog.runtime["cpu_memory_limit_bytes"]) if cpu else 0
            host["MemorySwap"] = host["Memory"] if cpu else 0
            host["PidsLimit"] = 256 if cpu else 2048
            host["ShmSize"] = 64 * 1024 * 1024 if cpu else 2 * 1024 * 1024 * 1024
            if not cpu:
                payload["Env"] += ["NVIDIA_DRIVER_CAPABILITIES=compute,utility", "VLLM_CACHE_ROOT=/root/.cache/vllm"]
                if catalog.runtime.get("adaptive") or getattr(self, "gpu_uuid", None) is not None:
                    payload["Env"].append("CUDA_VISIBLE_DEVICES=0")
            port = int(catalog.runtime["container_port"])
            payload["Healthcheck"] = {
                "Test": ["CMD", "python3", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health',timeout=2)"],
                "Interval": 5_000_000_000, "Timeout": 3_000_000_000, "Retries": 3,
            }
        async with self._client() as client:
            created = await client.post(
                "/containers/create",
                params={"name": self._template["name"]},
                json=payload,
                timeout=_DOCKER_API_TIMEOUT,
            )
            created.raise_for_status()
            new_id = created.json()["Id"]
            started = await client.post(f"/containers/{new_id}/start", timeout=_DOCKER_API_TIMEOUT)
            if started.status_code != 204:
                started.raise_for_status()

    async def validate(self, catalog: MainModelCatalog, profile: MainModelProfile) -> None:
        service = str(catalog.runtime["compose_service"])
        timeout = float(catalog.runtime.get("startup_timeout_seconds", 600))
        deadline = asyncio.get_running_loop().time() + timeout
        last_health = "unknown"
        while asyncio.get_running_loop().time() < deadline:
            container_id = await self._container_id(service)
            if container_id:
                inspected = await self._inspect(container_id)
                state = inspected.get("State", {})
                last_health = state.get("Health", {}).get("Status", state.get("Status", "unknown"))
                if last_health == "healthy":
                    break
                if state.get("Status") == "exited":
                    raise RuntimeError(
                        f"main runtime exited during startup: {state.get('ExitCode')}"
                    )
            await asyncio.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
        else:
            raise RuntimeError(f"main runtime did not become healthy: {last_health}")

        port = int(catalog.runtime["container_port"])
        base = f"http://{service}:{port}"
        async with httpx.AsyncClient(timeout=_RUNTIME_HTTP_TIMEOUT) as client:
            models = await client.get(base + str(catalog.runtime["models_path"]))
            models.raise_for_status()
            if profile.runtime_backend == "llama-cpp" and not any(
                row.get("id") == catalog.public_model and isinstance(row.get("meta"), dict)
                for row in models.json().get("data", []) if isinstance(row, dict)
            ):
                raise RuntimeError("CPU model identity or loaded metadata could not be verified")
            ids = {row.get("id") for row in models.json().get("data", [])}
            if catalog.public_model not in ids:
                raise RuntimeError(f"{catalog.public_model} missing from /v1/models")
            canary = await client.post(
                base + str(catalog.runtime["chat_path"]),
                json={
                    "model": catalog.public_model,
                    "messages": [{"role": "user", "content": "Reply with OK only."}],
                    "max_tokens": 8,
                    "temperature": 0,
                },
            )
            canary.raise_for_status()
            _validate_inference_canary(canary.json(), expected_model=catalog.public_model, kind="text")
            # Media boot canary: 해당 modality를 실제로 배포하는 profile에 대해서만
            # 수행한다. gate가 열리기 전에 런타임이 컨테이너 media를 디코드할 수
            # 있음을 증명하여, 지원한다고 표시되었지만 실제로는 깨진 modality가
            # 실제 요청에서 500을 내는 대신 rollback되도록 한다. 입력 modality의
            # 단일 source of truth는 capabilities.deployed_input이다. 같은 의미를
            # 별도 boolean flag로 중복 선언하지 않는다.
            deployed_modalities = set(profile.capabilities.get("deployed_input", []))
            if "image" in deployed_modalities:
                image_canary = await client.post(
                    base + str(catalog.runtime["chat_path"]),
                    json={
                        "model": catalog.public_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Reply with OK only."},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{_IMAGE_CANARY_JPEG_B64}"},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                )
                image_canary.raise_for_status()
                _validate_inference_canary(image_canary.json(), expected_model=catalog.public_model, kind="image")
            if "audio" in deployed_modalities:
                audio_canary = await client.post(
                    base + str(catalog.runtime["chat_path"]),
                    json={
                        "model": catalog.public_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Reply with OK only."},
                                    {
                                        "type": "input_audio",
                                        "input_audio": {"data": _AUDIO_CANARY_M4A_B64, "format": "m4a"},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                )
                audio_canary.raise_for_status()
                _validate_inference_canary(audio_canary.json(), expected_model=catalog.public_model, kind="audio")
            if "video" in deployed_modalities:
                video_canary = await client.post(
                    base + str(catalog.runtime["chat_path"]),
                    json={
                        "model": catalog.public_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Reply with OK only."},
                                    {
                                        "type": "video_url",
                                        "video_url": {"url": f"data:video/mp4;base64,{_VIDEO_CANARY_MP4_B64}"},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 8,
                        "temperature": 0,
                    },
                )
                video_canary.raise_for_status()
                _validate_inference_canary(video_canary.json(), expected_model=catalog.public_model, kind="video")
