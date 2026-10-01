from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "ops" / "compose" / "full-stack.private-network.yaml"


def test_compose_services_consume_shared_vllm_image_authority() -> None:
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = document["services"]

    for service in ("embedding-vllm", "embedding-ko-vllm", "prompt-injection-detector-runtime"):
        assert services[service]["image"].startswith("${VLLM_IMAGE:")
