#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="vLLM unified-image의 기준 설정에서 빌드 값을 출력합니다."
    )
    parser.add_argument(
        "--key",
        choices=("target_platform", "base_image", "vllm", "transformers", "huggingface_hub", "cuda_variant", "cuda_version"),
        default="transformers",
    )
    parser.add_argument("--variant", choices=("cu130", "cu129"),
                        default=os.environ.get("VLLM_BUILD_VARIANT", "cu130"))
    args = parser.parse_args()
    if args.variant not in {"cu130", "cu129"}:
        parser.error("VLLM_BUILD_VARIANT must be cu130 or cu129")
    document = yaml.safe_load(
        (ROOT / "configs/vllm_unified_build.yaml").read_text(encoding="utf-8")
    )
    if args.variant != "cu130":
        document = {**document, **document["build_variants"][args.variant]}
    if args.key == "cuda_variant":
        value = args.variant
    elif args.key == "cuda_version":
        value = document["cuda_version"]
    elif args.key == "target_platform":
        value = document["target_platform"]
    elif args.key == "base_image":
        value = document["base_image_default"]
    else:
        value = document["compatibility_pins"][args.key]
    print(str(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
