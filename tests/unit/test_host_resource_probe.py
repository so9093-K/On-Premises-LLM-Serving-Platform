"""실측 실패는 가용 GPU로 해석하지 않는다."""
def test_probe_does_not_guess_on_driver_query_failure(monkeypatch) -> None:
    import ai_model_serving.host_resource_probe as probe
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    def fails(*args, **kwargs):
        raise probe.subprocess.TimeoutExpired("nvidia-smi", timeout=3)
    monkeypatch.setattr(probe.subprocess, "run", fails)
    observed = probe.read_host_resource_snapshot()
    assert observed.gpus == ()
    assert observed.gpu_observation_error == "GPU_MEMORY_OBSERVATION_FAILED"
