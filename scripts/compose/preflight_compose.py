#!/usr/bin/env python3
"""Config-first full-stack compose preflight."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(line_buffering=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ai_model_serving.deployment_target import load_deployment_target  # noqa: E402
from ai_model_serving.main_model.boot import (  # noqa: E402
    render_boot_override,
    resolve_compose_relative_path,
)
from ai_model_serving.auth_control import (  # noqa: E402
    auth_profile_network_mismatch,
    local_only_host_bind_mismatches,
)
from ai_model_serving.access_profile import (  # noqa: E402
    access_profile_env_values,
    access_profile_mismatches,
)
from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file  # noqa: E402
from ai_model_serving.settings_parts.env import LOCAL_ENVIRONMENTS, resolve_env_file  # noqa: E402
from scripts.compose.effective_host_ports import effective_host_ports  # noqa: E402
from ai_model_serving.runtime_topology import load_runtime_topology  # noqa: E402
from scripts.compose.validate_vllm_compose import validate_alignment  # noqa: E402


def _fail(message: str) -> None:
    print(f"[preflight] fail: {message}", file=sys.stderr)


def _warn(message: str) -> None:
    print(f"[preflight] warn: {message}", file=sys.stderr)


def _env_value(
    key: str,
    default: str = "",
) -> str:
    env_path = resolve_env_file(os.environ.get("ENV_FILE"), ROOT)
    file_values: dict[str, str] = {}
    if env_path.exists():
        try:
            file_values = load_strict_env_file(env_path)
        except RuntimeError as exc:
            _fail(f"invalid env file: {env_path}")
            for line in str(exc).splitlines():
                print(f"  {line}", file=sys.stderr)
            print(
                "[preflight] Fix strict KEY=VALUE syntax before runtime checks. "
                "Duplicate keys, quotes, inline comments, and export syntax are not supported.",
                file=sys.stderr,
            )
            raise SystemExit("[preflight] configuration preflight failed; fix env file syntax.") from exc

    value = os.environ.get(key)
    if value is not None:
        return value
    return file_values.get(key, default)


def _non_local_app_env() -> bool:
    app_env = _env_value("APP_ENV", "local").strip().lower()
    return app_env not in LOCAL_ENVIRONMENTS


def _check_auth_profile_preflight() -> None:
    app_env = _env_value("APP_ENV", "local").strip()
    auth_mode = _env_value("AUTH_MODE", "local_open").strip() or "local_open"
    failures: list[str] = []
    access_profile = _env_value("ACCESS_PROFILE", "").strip()
    if access_profile:
        try:
            expected = access_profile_env_values(access_profile, ROOT)
            current = {
                key: _env_value(key, "")
                for key in expected
            }
            access_mismatches = access_profile_mismatches(access_profile, current, ROOT)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
        else:
            failures.extend(
                f"ACCESS_PROFILE={access_profile} drift: {message}"
                for message in access_mismatches
            )
    else:
        exposure_audience = _env_value("EXPOSURE_AUDIENCE", "")
        network_mismatch = auth_profile_network_mismatch(
            auth_mode, exposure_audience
        )
        if network_mismatch is not None:
            failures.append(network_mismatch + ".")
        elif auth_mode == "local_open" and exposure_audience == "local_only":
            failures.extend(
                local_only_host_bind_mismatches(
                    ROOT,
                    read_value=lambda key, default: _env_value(key, default),
                )
            )
    if not _non_local_app_env():
        if failures:
            for failure in failures:
                _fail(failure)
            raise SystemExit(
                "[preflight] configuration preflight failed; fix auth/exposure policy."
            )
        return
    if auth_mode == "custom":
        accepted = _env_value("CUSTOM_AUTH_RISK_ACCEPTED").lower() in {"1", "true"}
        ticket = _env_value("CUSTOM_AUTH_RISK_TICKET").strip()
        if not accepted or not ticket:
            failures.append(
                "AUTH_MODE=custom requires CUSTOM_AUTH_RISK_ACCEPTED=true and "
                "CUSTOM_AUTH_RISK_TICKET in non-local environments."
            )
    if failures:
        for failure in failures:
            _fail(failure)
        raise SystemExit("[preflight] configuration preflight failed; fix auth profile evidence before runtime checks.")
    print(f"[preflight] ok: AUTH_MODE={auth_mode} APP_ENV={app_env}")


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise SystemExit(f"[preflight] fail: cannot load {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"[preflight] fail: {label} must be a YAML mapping.")
    return data


def _phase0() -> None:
    print("[preflight] Phase 0: retired exposure compatibility")
    retired_mode = _env_value("EXPOSURE_MODE", "").strip()
    if retired_mode and retired_mode != "private_network":
        _fail(f"retired EXPOSURE_MODE={retired_mode!r} requires explicit Access migration.")
        raise SystemExit(
            "[preflight] choose ACCESS=local|private|edge and CONFIRM=access before runtime checks."
        )
    if retired_mode:
        _warn("EXPOSURE_MODE is retired and will be removed by env synchronization.")
    print("[preflight] ok: host exposure is the canonical private topology")


def _phase1() -> None:
    print("[preflight] Phase 1: access policy")
    _check_auth_profile_preflight()


def _compose_command(
    compose_args: list[str],
    env_file: str,
    project_name: str,
    *args: str,
) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project_name,
        *compose_args,
        "--env-file",
        env_file,
        *args,
    ]


def _compose_file_dir(compose_file: str) -> Path:
    path = Path(compose_file)
    return path.parent if path.is_absolute() else (ROOT / path).parent


def _run_status(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )


def _docker_compose_available() -> bool:
    if not shutil.which("docker"):
        print("[preflight] missing: docker", file=sys.stderr)
        return False
    print("[preflight] ok: docker found")
    result = _run_status(["docker", "compose", "version"], capture=True)
    if result.returncode != 0:
        print("[preflight] missing: docker compose plugin", file=sys.stderr)
        return False
    print("[preflight] ok: docker compose available")
    return True


def _show_gpu() -> bool:
    if not shutil.which("nvidia-smi"):
        _fail("nvidia-smi not found; the effective Compose stack requires an NVIDIA GPU")
        return False
    print("[preflight] ok: nvidia-smi found")
    result = _run_status(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
        capture=True,
    )
    if result.returncode != 0:
        _fail("nvidia-smi could not query an accessible NVIDIA GPU")
        return False
    for line in result.stdout.splitlines():
        print(f"[preflight] gpu: {line}")
    return True


def _gpu_services(document: dict[str, Any]) -> list[str]:
    """Return services whose effective Compose reservation requires a GPU."""

    required: list[str] = []
    for name, service in document.get("services", {}).items():
        if not isinstance(service, dict):
            continue
        devices = (
            service.get("deploy", {})
            .get("resources", {})
            .get("reservations", {})
            .get("devices", [])
        )
        for device in devices if isinstance(devices, list) else []:
            capabilities = device.get("capabilities", []) if isinstance(device, dict) else []
            flattened = {
                str(capability)
                for group in (capabilities if isinstance(capabilities, list) else [])
                for capability in (group if isinstance(group, list) else [group])
            }
            if "gpu" in flattened:
                required.append(str(name))
                break
    return required


def _compose_owned_ports(
    compose_args: list[str], env_file: str, project_name: str
) -> set[str]:
    result = _run_status(
        _compose_command(
            compose_args,
            env_file,
            project_name,
            "ps",
            "--format",
            "{{.Ports}}",
        ),
        capture=True,
    )
    if result.returncode != 0:
        return set()
    return set(re.findall(r"(?:\d+\.\d+\.\d+\.\d+|0\.0\.0\.0):(\d+)", result.stdout))


def _port_available(host_port: str, bind: str) -> bool:
    """Compose가 publish할 host port를 지금 잡을 수 있는지만 확인한다.

    bind는 가용성 판정 수단일 뿐이라 ``listen()``도 ``accept()``도 하지 않고 즉시
    닫는다. 연결을 받는 소켓이 아니므로 이 바인딩으로 도달할 수 있는 것은 없다.
    ``bind``는 Compose가 실제로 publish할 주소와 같아야 한다 -- 0.0.0.0으로 공개할
    포트를 127.0.0.1에서만 검사하면 다른 조건을 검사하는 것이 되어, 이미 점유된
    포트를 사용 가능하다고 보고한다.
    """
    sock = socket.socket()
    sock.settimeout(0.4)
    try:
        sock.bind((bind, int(host_port)))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def _effective_compose_document(
    compose_args: list[str], env_file: str, project_name: str
) -> dict[str, Any] | None:
    result = _run_status(
        _compose_command(compose_args, env_file, project_name, "config", "--format", "json"),
        capture=True,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        _fail(f"docker compose config could not resolve {' '.join(compose_args)} with --env-file {env_file}.")
        print(
            "[preflight] Fix compose env/file errors shown above before checking host port availability.",
            file=sys.stderr,
        )
        return None
    document = yaml.safe_load(result.stdout) or {}
    if not isinstance(document, dict):
        _fail("effective compose config must be a mapping")
        return None
    return document



def _prompt_runtime_effective() -> bool:
    target = load_deployment_target(
        ROOT / "configs/deployment_targets.yaml",
        _env_value("DEPLOYMENT_TARGET", "").strip() or None,
    )
    variant = _env_value("MAIN_MODEL_RESOURCE_VARIANT", "").strip() or None
    topology = load_runtime_topology(ROOT, main_resource_variant=variant)
    return "prompt_injection_detector" in topology.runtime_keys_for_features(
        target.features
    )


def _phase2(*, boot_override: Path) -> int:
    print("[preflight] Phase 2: compose and runtime checks")
    compose_file = os.environ.get("COMPOSE_FILE", "ops/compose/full-stack.private-network.yaml")
    env_path = resolve_env_file(os.environ.get("ENV_FILE"), ROOT).resolve()
    compose_path = Path(compose_file)
    compose_path = (
        compose_path if compose_path.is_absolute() else (ROOT / compose_path).resolve()
    )
    project_name = _env_value("COMPOSE_PROJECT_NAME", "ai-model-serving-platform") or "ai-model-serving-platform"
    os.environ["COMPOSE_PROJECT_NAME"] = project_name
    os.environ["COMPOSE_SERVICE_ENV_FILE"] = str(env_path)
    compose_args = ["-f", str(compose_path)]
    compose_args.extend(["-f", str(boot_override)])
    fail = False
    if not compose_path.is_file():
        print(f"[preflight] missing: base compose file {compose_file}", file=sys.stderr)
        fail = True
    elif not boot_override.is_file():
        _fail(f"missing main-model boot override: {boot_override}")
        return 1
    else:
        print("[preflight] ok: compose file set " + " ".join(compose_args))

    docker_ok = _docker_compose_available()
    fail = fail or not docker_ok
    if docker_ok and not fail:
        effective_document = _effective_compose_document(
            compose_args, str(env_path), project_name
        )
        if effective_document is None:
            fail = True
        else:
            gpu_services = _gpu_services(effective_document)
            if gpu_services:
                print("[preflight] effective Compose requires GPU: " + ", ".join(gpu_services))
                if not _show_gpu():
                    fail = True
            else:
                print("[preflight] effective Compose requires no GPU")
            try:
                validate_alignment(
                    compose_path,
                    effective_compose=effective_document,
                    boot_override=_load_yaml(boot_override, "main-model boot override"),
                )
            except SystemExit as exc:
                _fail(str(exc))
                fail = True

            owned_ports = _compose_owned_ports(
                compose_args, str(env_path), project_name
            )
            host_ports = list(effective_host_ports(effective_document))
            if not host_ports:
                print("[preflight] ok: effective compose config has no host-published ports")
            for service_name, host_port, bind in host_ports:
                if host_port in owned_ports:
                    print(f"[preflight] ok: port {host_port} ({service_name}) held by current compose stack")
                elif _port_available(host_port, bind):
                    print(f"[preflight] ok: port {host_port} ({service_name}) available on {bind}")
                else:
                    print(
                        f"[preflight] busy: port {host_port} ({service_name}) is already in use "
                        f"on {bind}",
                        file=sys.stderr,
                    )
                    fail = True
    elif not fail:
        _fail("cannot resolve effective compose ports without docker compose.")
        fail = True

    if _env_value("HF_TOKEN") or _env_value("HUGGING_FACE_HUB_TOKEN"):
        print("[preflight] ok: Hugging Face token env present")
    else:
        _warn("no HF_TOKEN/HUGGING_FACE_HUB_TOKEN found; private model pulls may fail")

    cache_raw = _env_value("HF_CACHE_DIR", "./model_cache/huggingface")
    cache_path = resolve_compose_relative_path(cache_raw, Path(compose_file))
    cache_path.mkdir(parents=True, exist_ok=True)
    if cache_path.is_dir() and os.access(cache_path, os.W_OK):
        print(f"[preflight] ok: HF cache dir writable: {cache_path}")
        print(f"[preflight] relative HF_CACHE_DIR values are resolved from compose file directory: {_compose_file_dir(compose_file)}")
    else:
        print(f"[preflight] missing: HF cache dir is not writable: {cache_path}", file=sys.stderr)
        fail = True

    if not _prompt_runtime_effective():
        print("[preflight] skip: Prompt detector runtime is not in the effective topology")
    elif os.environ.get("SKIP_RISK_VLLM_IMAGE_CONFIG_CHECK", "0") != "1":
        risk = _run_status(["bash", "scripts/models/check_risk_vllm_image_config.sh"])
        if risk.returncode == 0:
            print("[preflight] ok: risk vLLM image loads Kanana HF configs")
        else:
            print(
                "[preflight] risk vLLM image config check failed; build/check a Kanana-compatible "
                "RISK_VLLM_IMAGE or set SKIP_RISK_VLLM_IMAGE_CONFIG_CHECK=1 only for non-runtime local checks",
                file=sys.stderr,
            )
            fail = True
    else:
        print(
            "[preflight] skip: risk vLLM image config check disabled by "
            "SKIP_RISK_VLLM_IMAGE_CONFIG_CHECK=1",
            file=sys.stderr,
        )

    token_file = ROOT / ".runtime" / "prometheus" / "admin_api_key"
    if token_file.is_file() and token_file.stat().st_size > 0:
        print("[preflight] ok: Prometheus admin bearer-token file present")
    else:
        print(
            "[preflight] missing or invalid: .runtime/prometheus/admin_api_key must be a non-empty "
            "file; make up regenerates it before preflight",
            file=sys.stderr,
        )
        fail = True

    if fail:
        print(
            "[preflight] full-stack compose preflight failed; fix the items above before 'make up'.",
            file=sys.stderr,
        )
        return 1
    print("[preflight] full-stack compose preflight passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--boot-override", type=Path,
        help="Reuse the exact main-model override generated by compose-up",
    )
    args = parser.parse_args(argv)
    _phase0()
    _phase1()
    if args.boot_override is not None:
        return _phase2(boot_override=args.boot_override.resolve())
    # Standalone preflight uses the same boot resolver; never mutate persisted state.
    with tempfile.TemporaryDirectory(prefix="preflight-boot-") as directory:
        env_path = resolve_env_file(os.environ.get("ENV_FILE"), ROOT)
        _, document = render_boot_override(
            catalog_path=ROOT / "configs/main_model_profiles.yaml",
            state_path=ROOT / ".runtime/main-model/main-model-state.json",
            env_path=env_path,
        )
        boot_override = Path(directory) / "boot.yaml"
        boot_override.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return _phase2(boot_override=boot_override)


if __name__ == "__main__":
    raise SystemExit(main())
