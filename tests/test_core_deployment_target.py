"""GPU 모델 자원이 없는 배포의 계약을 보호한다."""
from pathlib import Path

from ai_model_serving.deployment_target import load_deployment_target

ROOT = Path(__file__).resolve().parents[1]


def test_core_target_does_not_require_model_runtime() -> None:
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-core")
    assert target.implementation_status == "implemented"
    assert target.runtime_backend == "none"
    assert target.main_profile_catalog is None
    assert not target.supports("chat")
    assert target.supports("risk")
    assert not target.supports("gpu_admission")
    assert target.control_mode == "static"
    assert target.compose_files


def test_gpu_target_retains_existing_model_contract() -> None:
    target = load_deployment_target(ROOT / "configs/deployment_targets.yaml", "linux-nvidia-dynamic")
    assert target.supports("chat")
    assert target.supports("gpu_admission")
    assert target.main_profile_catalog == "configs/main_model_profiles.yaml"
