from __future__ import annotations

from pathlib import Path

import yaml

from ai_model_serving.platform_state import DEFAULT_PLATFORM_STATE_DIR


_ROOT = Path(__file__).resolve().parents[2]
_STATE_ROOT = str(DEFAULT_PLATFORM_STATE_DIR)
_STATE_BIND = f"../../.runtime/gateway:{_STATE_ROOT}"


def _compose(path: str) -> dict:
    return yaml.safe_load((_ROOT / path).read_text(encoding="utf-8"))


def test_static_and_dynamic_gateway_share_platform_state_contract() -> None:
    static_gateway = _compose("ops/compose/static-main.external-runtime.yaml")["services"]["gateway"]
    dynamic_gateway = _compose("ops/compose/full-stack.private-network.yaml")["services"]["gateway"]

    assert static_gateway["environment"]["PLATFORM_STATE_DIR"] == _STATE_ROOT
    assert dynamic_gateway["environment"]["PLATFORM_STATE_DIR"] == _STATE_ROOT
    assert _STATE_BIND in static_gateway["volumes"]
    assert _STATE_BIND in dynamic_gateway["volumes"]
