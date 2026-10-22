"""실제 선택 이미지의 CUDA 계열과 호스트 드라이버의 최소 조건을 검사한다.

NVIDIA minor-version-compatibility의 하한만 검사한다. PTX/JIT와 실제 모델의
실행 가능 여부는 후속 Canary가 소유한다.
"""

import re


def driver_compatibility_error(image: dict, driver: str | None) -> str | None:
    config = image.get("Config") or {}
    variant = (config.get("Labels") or {}).get("ai_model_serving.cuda_variant", "")
    environment = dict(item.split("=", 1) for item in config.get("Env") or [] if "=" in item)
    # 새 이미지는 빌드에서 실제 Torch CUDA와 대조한 라벨을 사용한다.
    # 이전 이미지는 Docker 환경의 CUDA_VERSION을 사용하며 태그 이름으로 추측하지 않는다.
    cuda = {"cu129": "12.9", "cu130": "13.0"}.get(variant, environment.get("CUDA_VERSION", ""))
    cuda_match = re.fullmatch(r"(\d+)\.\d+(?:\.\d+)?", cuda)
    driver_match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", driver or "")
    if cuda_match is None or driver_match is None:
        return "GPU_DRIVER_COMPATIBILITY_UNKNOWN"
    # https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html
    minimum = {12: (525, 60, 13), 13: (580, 0, 0)}.get(int(cuda_match[1]))
    if minimum is None:
        return "GPU_DRIVER_COMPATIBILITY_UNKNOWN"
    version = tuple(int(part or 0) for part in driver_match.groups())
    return "GPU_DRIVER_INCOMPATIBLE" if version < minimum else None
