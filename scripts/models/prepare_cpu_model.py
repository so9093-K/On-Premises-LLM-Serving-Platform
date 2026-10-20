#!/usr/bin/env python3
"""고정 CPU 모델의 준비는 Main Model Artifact 경계에서 수행한다."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from ai_model_serving.main_model.cpu import prepare_cpu_model  # noqa: E402


def main() -> int:
    try:
        prepare_cpu_model(config_root=ROOT)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f'[cpu-model] fail: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
