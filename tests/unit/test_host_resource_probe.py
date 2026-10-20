"""GPU 탐지와 실제 가용 자원이 다를 수 있는 배포 후보 계약을 검증한다."""
from ai_model_serving.host_resource_probe import (
    GpuMemory, HostResourceSnapshot, read_host_resource_snapshot,
    recommend_initial_target,
)


POLICY = {"startup": {
    "gpu_min_total_vram_mib": 20480,
    "gpu_min_free_vram_mib": 19000,
    "cpu_min_available_ram_mib": 4096,
    "preferred_gpu_target": "linux-nvidia-dynamic",
    "preferred_cpu_target": "linux-cpu-managed",
    "no_inference_target": "linux-core",
}}


def test_gpu_present_but_occupied_prefers_cpu() -> None:
    snapshot = HostResourceSnapshot((GpuMemory(0, 24564, 2100),), 8192)
    target, reason = recommend_initial_target(snapshot, POLICY)
    assert target == "linux-cpu-managed"
    assert "GPU model candidate unavailable" in reason


def test_gpu_sufficient_is_only_candidate() -> None:
    snapshot = HostResourceSnapshot((GpuMemory(0, 24564, 22000),), 8192)
    target, reason = recommend_initial_target(snapshot, POLICY)
    assert target == "linux-nvidia-dynamic"
    assert "real runtime admission required" in reason


def test_no_gpu_no_ram_prefers_core() -> None:
    target, _ = recommend_initial_target(HostResourceSnapshot((), None), POLICY)
    assert target == "linux-core"


def test_unknown_gpu_observation_is_not_treated_as_free() -> None:
    target, _ = recommend_initial_target(
        HostResourceSnapshot((), 4096, "GPU_MEMORY_OBSERVATION_FAILED"), POLICY
    )
    assert target == "linux-cpu-managed"


def test_probe_does_not_guess_on_driver_query_failure(monkeypatch) -> None:
    import ai_model_serving.host_resource_probe as probe
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    def fails(*args, **kwargs):
        raise probe.subprocess.TimeoutExpired("nvidia-smi", timeout=3)
    monkeypatch.setattr(probe.subprocess, "run", fails)
    observed = read_host_resource_snapshot()
    assert observed.gpus == ()
    assert observed.gpu_observation_error == "GPU_MEMORY_OBSERVATION_FAILED"
