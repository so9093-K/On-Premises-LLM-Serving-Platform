from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_CONTEXT = ROOT / "scripts" / "lib" / "compose_context.sh"
COMPOSE_FILE = ROOT / "ops" / "compose" / "full-stack.private-network.yaml"


def _bash(command: str) -> subprocess.CompletedProcess[str]:
    process_env = dict(os.environ)
    for key in (
        "VLLM_IMAGE",
        "EMBEDDING_KO_VLLM_IMAGE",
        "RISK_VLLM_IMAGE",
    ):
        process_env.pop(key, None)
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_compose_services_consume_shared_vllm_image_authority() -> None:
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = document["services"]

    for service in ("embedding-vllm", "embedding-ko-vllm", "prompt-injection-detector-runtime"):
        assert services[service]["image"].startswith("${VLLM_IMAGE:")


def test_compose_context_does_not_materialize_retired_runtime_image_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "COMPOSE_PROJECT_NAME=test-project\n"
        "VLLM_IMAGE=registry.example.com/vllm@sha256:shared\n",
        encoding="utf-8",
    )
    result = _bash(
        f"source {shlex.quote(str(COMPOSE_CONTEXT))}; "
        f"PYTHON_BIN={shlex.quote(sys.executable)}; "
        f"ENV_FILE={shlex.quote(str(env_file))}; "
        f"COMPOSE_FILE={shlex.quote(str(COMPOSE_FILE))}; "
        "compose_context_init \"$PWD\"; "
        "printf '%s|%s' \"${EMBEDDING_KO_VLLM_IMAGE+x}\" \"${RISK_VLLM_IMAGE+x}\""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "|"
