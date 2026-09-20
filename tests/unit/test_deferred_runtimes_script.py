"""배포 프로필의 기본 선택과 명시적 override 우선순위를 검증한다."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/runtime/deferred_runtimes.py"
DISABLED_SCRIPT = ROOT / "scripts/runtime/disabled_runtime_services.py"


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


def run_disabled_script(config_root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DISABLED_SCRIPT), "--config-root", str(config_root)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_disabled_runtime_services_are_reported_for_compose_exclusion():
    # compose-up은 기동 집합을 "전체 서비스 빼기 deferred"로 만든다. 비활성 binding은
    # controllable일 수 없어 deferred 목록에 들어가지 못하므로, 이 목록이 비면
    # 비활성 runtime이 그대로 기동해 GPU를 점유한 뒤 실패한다.
    result = run_disabled_script()
    services = result.stdout.split()
    assert "prompt-injection-detector-runtime" in services


def test_disabled_runtime_services_are_empty_when_every_binding_is_enabled(tmp_path):
    import shutil

    import yaml

    (tmp_path / "configs").mkdir()
    for name in ("runtime_topology.yaml", "services.yaml", "model_serving.yaml"):
        shutil.copy(ROOT / "configs" / name, tmp_path / "configs" / name)
    path = tmp_path / "configs" / "runtime_topology.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for binding in document["runtimes"].values():
        binding["enabled"] = True
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    serving_path = tmp_path / "configs" / "model_serving.yaml"
    serving = yaml.safe_load(serving_path.read_text(encoding="utf-8"))
    for runtime in serving["models"].values():
        runtime["enabled"] = True
    serving_path.write_text(yaml.safe_dump(serving), encoding="utf-8")

    result = run_disabled_script(tmp_path)
    assert result.stdout.split() == []
