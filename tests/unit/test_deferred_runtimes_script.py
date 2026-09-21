"""배포 프로필의 기본 선택과 명시적 override 우선순위를 검증한다."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/runtime/deferred_runtimes.py"
DISABLED_SCRIPT = ROOT / "scripts/runtime/disabled_runtime_services.py"

from ai_model_serving.runtime_topology import load_runtime_topology
from scripts.runtime.deferred_runtimes import resolve_deferred_runtimes


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
        "keys": ["embedding", "embedding_ko", "prompt_injection_detector"],
        "services": [
            "embedding-vllm",
            "embedding-ko-vllm",
            "prompt-injection-detector-runtime",
        ],
        "profile": "main_only",
    }


def test_explicit_profile_overrides_default_profile():
    result = run_script("--profile", "retrieval_ready", "--output", "json")

    payload = json.loads(result.stdout)
    assert payload["keys"] == ["prompt_injection_detector"]
    assert payload["services"] == ["prompt-injection-detector-runtime"]
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


def run_disabled_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DISABLED_SCRIPT), "--config-root", str(ROOT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_reference_policy_has_no_disabled_runtime_services():
    assert run_disabled_script().stdout.split() == []


def test_4090_resource_policy_excludes_prompt_detector_from_compose_start():
    result = run_disabled_script(
        "--main-resource-variant", "rtx4090-24gb"
    )
    assert result.stdout.split() == ["prompt-injection-detector-runtime"]


def test_startup_profile_ignores_runtime_unavailable_under_resource_policy():
    result = run_script(
        "--main-resource-variant",
        "rtx4090-24gb",
        "--output",
        "json",
    )
    payload = json.loads(result.stdout)
    assert payload == {
        "keys": ["embedding", "embedding_ko"],
        "services": ["embedding-vllm", "embedding-ko-vllm"],
        "profile": "main_only",
    }


def test_profile_resolution_does_not_hide_known_noncontrollable_runtime():
    topology = load_runtime_topology(ROOT)

    with pytest.raises(SystemExit, match="unknown or unavailable deferred runtime"):
        resolve_deferred_runtimes(
            topology,
            "main_llm",
            ignore_unavailable=True,
        )
