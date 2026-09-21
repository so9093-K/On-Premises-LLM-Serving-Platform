"""Runtime topology에서 비활성으로 선언된 runtime의 Compose 서비스 이름을 출력한다.

Compose 파일은 runtime이 비활성이어도 그 서비스 정의를 계속 들고 있다. 정의를 지우면
services.yaml의 service registry, exposure profile의 host_published 집합, 그리고
diagnostic profile이 모든 model_runtime을 공개해야 한다는 규칙까지 연쇄로 함께
바꿔야 하고, 다시 켤 때 그 전부를 복원해야 한다.

그래서 정의는 남기고 기동 대상에서만 뺀다. 이 목록이 없으면 compose-up이 "전체 서비스
빼기 deferred"로 기동 집합을 만들기 때문에, 비활성 runtime이 그대로 기동해 GPU를
점유한 뒤 실패한다. 비활성 binding은 controllable일 수 없어 deferred 목록에도 들어갈
수 없으므로 이 경로가 유일한 제외 수단이다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ai_model_serving.runtime_topology import load_runtime_topology  # noqa: E402


def disabled_runtime_services(
    config_root: Path, *, main_resource_variant: str | None = None
) -> list[str]:
    topology = load_runtime_topology(
        config_root, main_resource_variant=main_resource_variant
    )
    return sorted(
        binding.compose_service
        for binding in topology.bindings_by_key.values()
        if not binding.enabled and binding.compose_service
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", default=str(ROOT))
    parser.add_argument(
        "--main-resource-variant",
        default=os.getenv("MAIN_MODEL_RESOURCE_VARIANT", ""),
    )
    args = parser.parse_args()
    variant = args.main_resource_variant.strip() or None
    for service in disabled_runtime_services(
        Path(args.config_root), main_resource_variant=variant
    ):
        print(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
