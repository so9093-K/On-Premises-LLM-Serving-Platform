"""검증 후보의 lock과 설치 패키지 일치가 GPU 실행 검사보다 먼저 확정된다."""
from pathlib import Path

import pytest

from scripts.build import verify_cuda129_image as verification

ROOT = Path(__file__).resolve().parents[2]


def test_cuda129_locks_are_the_version_authority():
    expected = verification.locked_versions([
        ROOT / "ops/images/vllm-unified" / name for name in verification.LOCK_NAMES
    ])
    verification.verify_versions(expected, expected.copy())
    mixed = {**expected, "torch": "2.14.0+cu130"}
    with pytest.raises(ValueError, match="dependency mismatch: torch"):
        verification.verify_versions(expected, mixed)
    with pytest.raises(ValueError, match="dependency mismatch: triton"):
        verification.verify_versions(expected, {**expected, "triton": "3.8.0"})
    with pytest.raises(ValueError, match="dependency mismatch: cuda-bindings"):
        verification.verify_versions(expected, {**expected, "cuda-bindings": "13.4.2"})


@pytest.mark.parametrize("line", ["torch>=2.13.0", "torch==2.13.0", "--extra-index-url https://example.com"])
def test_candidate_locks_reject_unpinned_or_unhashed_dependencies(tmp_path, line):
    path = tmp_path / "requirements.lock"
    path.write_text(line)
    with pytest.raises(ValueError, match="invalid or duplicate dependency pin"):
        verification.locked_versions([path])


def test_empty_and_duplicate_candidate_locks_fail(tmp_path):
    path = tmp_path / "requirements.lock"
    path.write_text("# empty\n")
    with pytest.raises(ValueError, match="empty"):
        verification.locked_versions([path])
    pin = "torch==2.13.0+cu129 --hash=sha256:" + "a" * 64 + "\n"
    path.write_text(pin + pin)
    with pytest.raises(ValueError, match="duplicate"):
        verification.locked_versions([path])
