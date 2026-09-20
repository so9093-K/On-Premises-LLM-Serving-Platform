"""배포 프로필의 기본 선택과 명시적 override 우선순위를 검증한다."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/runtime/deferred_runtimes.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config-root", str(ROOT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_default_profile_defers_all_non_main_runtimes():
    result = run_script("--output", "json")

    payload = json.loads(result.stdout)
    assert payload == {
        "keys": ["embedding", "embedding_ko"],
        "services": ["embedding-vllm", "embedding-ko-vllm"],
        "profile": "main_only",
    }


def test_explicit_profile_overrides_default_profile():
    # retrieval_ready는 아무것도 미루지 않는다. 기본 profile이 embedding 두 종을
    # 미루므로, 빈 결과 자체가 override가 실제로 적용됐다는 증거다.
    result = run_script("--profile", "retrieval_ready", "--output", "json")

    payload = json.loads(result.stdout)
    assert payload["keys"] == []
    assert payload["services"] == []
    assert payload["profile"] == "retrieval_ready"


def test_direct_runtime_list_overrides_profile():
    result = run_script(
        "--profile", "main_only", "--runtimes", "embedding", "--output", "json"
    )

    assert json.loads(result.stdout) == {
        "keys": ["embedding"],
        "services": ["embedding-vllm"],
        "profile": "",
    }
