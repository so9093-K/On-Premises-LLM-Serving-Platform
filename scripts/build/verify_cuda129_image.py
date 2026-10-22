#!/usr/bin/env python3
"""CUDA 12.9 후보의 패키지 일치와 선택적인 실제 GPU 연산을 검증한다."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path

LOCK_ROOT = Path("/usr/local/share/ai-model-serving/cu129")
LOCK_NAMES = ("requirements.cu129-pytorch.lock", "requirements.cu129-runtime.lock")
PIN = re.compile(r"^([\w.-]+)==([^\s]+) --hash=sha256:[0-9a-f]{64}$")


def locked_versions(paths: list[Path]) -> dict[str, str]:
    """검증 기대값도 설치에 사용한 해시 lock에서 읽는다."""
    expected: dict[str, str] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            match = PIN.fullmatch(line)
            if not match or match[1] in expected:
                raise ValueError(f"invalid or duplicate dependency pin: {path}: {line}")
            expected[match[1]] = match[2]
    if not expected:
        raise ValueError("CUDA 12.9 dependency locks are empty")
    return expected


def verify_versions(expected: dict[str, str], actual: dict[str, str]) -> None:
    for name, version in expected.items():
        if actual.get(name) != version:
            raise ValueError(f"dependency mismatch: {name} expected={version} actual={actual.get(name)}")


def verify_gpu(torch, torchvision) -> dict:
    """소량 메모리로 CUDA·확장 ABI·Triton JIT를 실제 실행한다."""
    torch.cuda.init()
    value = torch.ones((256, 256), device="cuda", dtype=torch.float16)
    assert torch.allclose(value @ value, torch.full_like(value, 256))
    compiled = torch.compile(lambda x: x.sin() + x * 2, fullgraph=True)
    assert torch.allclose(compiled(value), value.sin() + value * 2, atol=0.01, rtol=0.01)
    boxes = torch.tensor([[0., 0., 1., 1.], [0., 0., 1., 1.]], device="cuda")
    scores = torch.tensor([0.9, 0.8], device="cuda")
    assert torchvision.ops.nms(boxes, scores, 0.5).tolist() == [0]
    importlib.import_module("vllm._C_stable_libtorch")
    torch.cuda.synchronize()
    driver = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True,
    ).strip()
    return {"name": torch.cuda.get_device_name(), "driver": driver,
            "checks": ["matmul", "triton-jit", "torchvision-nms", "vllm-extension"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CUDA 12.9 후보 이미지의 실행 의존성을 확인합니다.")
    parser.add_argument("--gpu", action="store_true", help="실제 GPU에서 CUDA와 JIT 연산까지 실행")
    args = parser.parse_args(argv)
    try:
        expected = locked_versions([LOCK_ROOT / name for name in LOCK_NAMES])
        actual = {name: importlib.metadata.version(name) for name in expected}
        verify_versions(expected, actual)
        vllm = importlib.import_module("vllm")
        torch = importlib.import_module("torch")
        torchvision = importlib.import_module("torchvision")
        importlib.import_module("torchaudio")
        importlib.import_module("torchcodec")
        if torch.version.cuda != "12.9" or vllm.__version__.partition("+")[0] != "0.30.0":
            raise ValueError(f"unexpected runtime: CUDA={torch.version.cuda}, vLLM={vllm.__version__}")
        subprocess.run([sys.executable, "-m", "pip", "check"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        report = {"cuda": torch.version.cuda, "vllm": vllm.__version__, "packages": actual}
        if args.gpu:
            report["gpu"] = verify_gpu(torch, torchvision)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, ImportError, RuntimeError, AssertionError,
            subprocess.CalledProcessError, importlib.metadata.PackageNotFoundError) as exc:
        detail = exc.stdout if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"[cu129] 검증 실패: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
