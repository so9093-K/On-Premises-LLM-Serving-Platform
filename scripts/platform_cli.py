#!/usr/bin/env python3
"""Target-aware local lifecycle command.

The operator workflow is intent-based: up/down/status. This module owns target
selection and convergence; existing scripts remain implementation details.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ai_model_serving.deployment_target import DeploymentTarget, load_deployment_target  # noqa: E402
from ai_model_serving.configuration import load_yaml_mapping  # noqa: E402
from ai_model_serving.access_profile import (  # noqa: E402
    access_profile_mismatches,
    access_profile_names,
    load_access_profile,
)
from ai_model_serving.settings_parts.dotenv_parser import load_strict_env_file  # noqa: E402
from ai_model_serving.settings_parts.env import DEFAULT_ENV_FILENAME, default_env_path  # noqa: E402
from scripts.build.pin_local_vllm_image import (  # noqa: E402
    pin_matching_env_values,
    resolve_local_image_id,
)

TARGETS_PATH = ROOT / "configs" / "deployment_targets.yaml"
SERVICES_PATH = ROOT / "configs" / "services.yaml"
ENV_PATH = default_env_path(ROOT)


def _run(*command: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def _operator_log_path(label: str) -> Path:
    safe = "".join(char if char.isalnum() else "-" for char in label.lower()).strip("-")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = ROOT / ".runtime" / "operator-logs" / f"{stamp}-{safe}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_step(label: str, *command: str, env: dict[str, str] | None = None) -> None:
    """Run an implementation step without turning its raw output into the operator UI."""
    if os.environ.get("PLATFORM_VERBOSE") == "1":
        print(f"[platform] {label}...")
        _run(*command, env=env)
        print(f"[platform] ✓ {label}")
        return

    path = _operator_log_path(label)
    print(f"[platform] {label}...")
    with path.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if result.returncode == 0:
        path.unlink(missing_ok=True)
        print(f"[platform] ✓ {label}")
        return

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    excerpt = "\n".join(lines[-20:])
    detail = f"\n{excerpt}" if excerpt else ""
    raise RuntimeError(
        f"{label} failed (exit {result.returncode}){detail}\n"
        f"full output: {path.relative_to(ROOT)}"
    )


def _env_values() -> dict[str, str]:
    if not ENV_PATH.is_file():
        raise RuntimeError(".env is missing; run make up TARGET=<deployment-target> first")
    return load_strict_env_file(ENV_PATH)


def _target(explicit: str | None, *, require_env: bool = True) -> DeploymentTarget:
    values = _env_values() if ENV_PATH.is_file() else {}
    configured = values.get("DEPLOYMENT_TARGET")
    if explicit and configured and explicit != configured:
        raise RuntimeError(
            f"requested target {explicit!r} differs from .env target {configured!r}; "
            "move the existing .env aside before initializing another target"
        )
    selected = explicit or configured
    if not selected:
        if require_env:
            raise RuntimeError("first run requires make up TARGET=<deployment-target>")
        raise RuntimeError("TARGET is required for the first make up")
    return load_deployment_target(TARGETS_PATH, selected)


def _main_profile(target: DeploymentTarget, values: dict[str, str]) -> str:
    key = "MAIN_MODEL_STATIC_PROFILE" if target.control_mode == "static" else "MAIN_MODEL_BOOT_PROFILE"
    profile = values.get(key, "")
    if not profile:
        raise RuntimeError(f"{key} is missing from .env; rerun make up for target {target.target_id}")
    return profile


def _print_access(values: dict[str, str]) -> None:
    name = values.get("ACCESS_PROFILE", "").strip()
    if not name:
        print(
            "[platform] access: legacy/custom "
            f"(auth={values.get('AUTH_MODE', '<unset>')} "
            f"exposure={values.get('EXPOSURE_MODE', '<unset>')})"
        )
        return
    profile = load_access_profile(name)
    mismatches = access_profile_mismatches(name, values)
    if mismatches:
        raise RuntimeError(
            f"ACCESS_PROFILE={name!r} drift: " + "; ".join(mismatches)
        )
    print(
        f"[platform] access: {profile.name} — {profile.description} "
        f"(auth={values.get('AUTH_MODE')} exposure={values.get('EXPOSURE_MODE')})"
    )


def _gateway_probe(values: dict[str, str], path: str) -> tuple[str, bool]:
    host = values.get("GATEWAY_BIND_ADDR") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    services = load_yaml_mapping(SERVICES_PATH).get("services", {})
    gateway = services.get("gateway") if isinstance(services, dict) else None
    if not isinstance(gateway, dict) or "default_host_port" not in gateway:
        raise RuntimeError("configs/services.yaml gateway.default_host_port is missing")
    port = values.get("GATEWAY_PORT") or str(gateway["default_host_port"])
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return url, response.status == 200
    except (OSError, urllib.error.URLError):
        return url, False


def _wait_for_gateway(values: dict[str, str], path: str, timeout: int = 60) -> str:
    deadline = time.monotonic() + timeout
    while True:
        url, ready = _gateway_probe(values, path)
        if ready:
            return url
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Gateway did not become healthy within {timeout}s at {url}")
        time.sleep(1)


def setup_target(
    target: DeploymentTarget,
    main_profile: str | None,
    main_base_url: str | None,
    access_profile: str | None,
    confirm_access: bool,
) -> bool:
    if target.runtime_backend == "mlx-vlm":
        _run_step(
            "Checking Metal runtime prerequisites",
            sys.executable,
            "scripts/runtime/macos_mlx_runtime.py",
            "doctor",
        )
    if ENV_PATH.exists():
        command = [
            sys.executable,
            "scripts/config/setup_env.py",
            "--sync-env", "--env-file", DEFAULT_ENV_FILENAME,
            "--deployment-target", target.target_id,
        ]
        if main_profile:
            command += ["--main-profile", main_profile]
        if main_base_url:
            command += ["--main-llm-base-url", main_base_url]
        if access_profile:
            command += ["--access-profile", access_profile]
        if confirm_access:
            command += ["--confirm-access"]
        _run_step("Synchronizing platform configuration", *command)
        if access_profile:
            current = _env_values()
            if access_profile_mismatches(access_profile, current):
                print(
                    "[platform] access plan complete; existing .env was not changed. "
                    "Review the plan, then rerun with CONFIRM=access."
                )
                return False
        print(f"[platform] configuration ready: target={target.target_id}")
    else:
        command = [
            sys.executable,
            "scripts/config/setup_env.py",
            "--profile", "compose",
            "--deployment-target", target.target_id,
        ]
        if main_profile:
            command += ["--main-profile", main_profile]
        if main_base_url:
            command += ["--main-llm-base-url", main_base_url]
        if access_profile:
            command += ["--access-profile", access_profile]
        if target.control_mode == "static" and not target.gateway_runtime_host and not main_base_url:
            raise RuntimeError(
                f"static target {target.target_id!r} needs MAIN_URL=http(s)://... on first make up"
            )
        _run_step("Creating platform configuration", *command)

    if target.runtime_backend == "mlx-vlm":
        _run_step(
            "Preparing Metal runtime environment",
            sys.executable,
            "scripts/runtime/macos_mlx_runtime.py",
            "setup",
        )
    _print_access(_env_values())
    return True


def _registry_digest(image: str) -> bool:
    """Return whether the ref identifies an externally published artifact.

    A bare ``sha256:...`` is a local Docker image ID produced by this lifecycle.
    It must remain rebuildable; only a named registry digest is external input.
    """
    return "@sha256:" in image


def _source_provenance() -> tuple[str, str]:
    if not (ROOT / ".git").exists():
        return "unknown", "unknown"
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if revision.returncode != 0:
        return "unknown", "unknown"
    state = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return revision.stdout.strip(), "dirty" if state.stdout.strip() else "clean"


def _local_image_matches_source(image: str) -> bool:
    if not image or _registry_digest(image):
        return False
    inspected = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if inspected.returncode != 0:
        return False
    try:
        labels = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(labels, dict):
        return False
    revision, state = _source_provenance()
    if revision == "unknown":
        return True
    if state != "clean":
        return False
    return (
        labels.get("org.opencontainers.image.revision") == revision
        and labels.get("ai_model_serving.source_state") == "clean"
    )


def ensure_target_artifacts(target: DeploymentTarget) -> None:
    values = _env_values()
    refs: list[tuple[str, str]] = [("Platform image", values.get("PLATFORM_IMAGE", ""))]
    if target.controllable:
        refs.append(("Unified vLLM image", values.get("VLLM_IMAGE", "")))

    stale = False
    for label, image in refs:
        if _registry_digest(image):
            print(f"[platform] ✓ {label}: external immutable digest")
            continue
        if _local_image_matches_source(image):
            print(f"[platform] ✓ {label}: current local source")
            continue
        stale = True

    if stale:
        build_target(target)
    else:
        print(f"[platform] ✓ Build artifacts: target={target.target_id}")


def build_target(target: DeploymentTarget, *, no_cache: bool = False) -> None:
    values = _env_values()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    built: list[str] = []
    external: list[str] = []
    platform_image = values.get("PLATFORM_IMAGE", "")
    if _registry_digest(platform_image):
        external.append("platform")
        print(f"[platform] preserving external Platform image: {platform_image}")
    else:
        source_ref = platform_image
        build_ref = platform_image
        if not build_ref or build_ref.startswith("sha256:"):
            build_ref = f"ai-model-serving-platform:{version}"
        build_env = dict(os.environ)
        build_env["PLATFORM_IMAGE"] = build_ref
        if no_cache:
            build_env["PROJECT_BUILD_NO_CACHE"] = "1"
        _run_step("Building Platform image", "bash", "scripts/build/build_platform_image.sh", env=build_env)
        built.append("platform")
        if source_ref.startswith("sha256:"):
            new_image_id = resolve_local_image_id(build_ref)
            pin_matching_env_values(
                ENV_PATH,
                source_ref,
                new_image_id,
                keys=("PLATFORM_IMAGE",),
            )
            print(f"[platform] pinned local Platform image: PLATFORM_IMAGE={new_image_id}")

    if target.controllable:
        image = values.get("VLLM_IMAGE", "")
        if _registry_digest(image):
            external.append("vllm-unified")
            print(f"[platform] preserving external Unified vLLM image: {image}")
        else:
            build_ref = image
            if not build_ref or build_ref.startswith("sha256:"):
                build_ref = f"ai-model-serving-vllm-unified:{version}"
            build_env = dict(os.environ)
            build_env["VLLM_UNIFIED_BUILD_IMAGE"] = build_ref
            if no_cache:
                build_env["PROJECT_BUILD_NO_CACHE"] = "1"
            _run_step(
                "Building Unified vLLM image",
                "bash",
                "scripts/build/build_vllm_unified_image.sh",
                env=build_env,
            )
            new_image_id = resolve_local_image_id(build_ref)
            updated = pin_matching_env_values(ENV_PATH, image or build_ref, new_image_id)
            print(f"[platform] pinned local Unified image: {','.join(sorted(updated))}={new_image_id}")
            built.append("vllm-unified")

    mode = "rebuilt without cache reuse" if no_cache else "built with cache reuse"
    built_text = ",".join(built) if built else "none"
    external_text = ",".join(external) if external else "none"
    print(
        f"[platform] target artifacts: {mode}; built={built_text}; "
        f"external-preserved={external_text}; target={target.target_id}"
    )


def prepare_target(target: DeploymentTarget) -> None:
    values = _env_values()
    if target.runtime_backend == "mlx-vlm":
        _run_step(
            "Preparing Main Model cache",
            sys.executable,
            "scripts/runtime/macos_mlx_runtime.py",
            "prepare",
        )
    elif target.controllable:
        profile = _main_profile(target, values)
        _run_step(
            "Preparing Main Model cache",
            sys.executable,
            "scripts/models/prepare_main_model_cache.py",
            "--profile",
            profile,
            "--env-file",
            DEFAULT_ENV_FILENAME,
        )
    else:
        print("[platform] external Main runtime is not built or downloaded by this target")
    print(f"[platform] model inputs ready: target={target.target_id}")


def up_target(target: DeploymentTarget) -> None:
    values = _env_values()
    if values.get("BUILD_PROFILE") == "local":
        _run_step("Starting application services", "bash", "scripts/ops/up_services.sh")
        url = _wait_for_gateway(values, "/health")
        print(f"[platform] ready: app-only gateway={url}")
        return
    metal_started_here = False
    if target.runtime_backend == "mlx-vlm":
        status = subprocess.run(
            [sys.executable, "scripts/runtime/macos_mlx_runtime.py", "status"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        _run_step(
            "Starting Metal Main Model runtime",
            sys.executable,
            "scripts/runtime/macos_mlx_runtime.py",
            "start-background",
        )
        metal_started_here = status.returncode != 0
    try:
        if target.control_mode == "static":
            process_env = {**os.environ, "DEPLOYMENT_TARGET": target.target_id}
            _run_step(
                "Starting platform services",
                "bash",
                "scripts/compose/static_main_compose.sh",
                "up",
                "-d",
                env=process_env,
            )
        else:
            _run_step("Starting platform services", "bash", "scripts/compose/compose_up.sh")
            _run_step("Verifying serving readiness", "bash", "scripts/ops/ready_full.sh")
        url = _wait_for_gateway(values, "/ready")
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        if metal_started_here:
            subprocess.run(
                [sys.executable, "scripts/runtime/macos_mlx_runtime.py", "stop"],
                cwd=ROOT,
                check=False,
            )
        raise

    print(f"[platform] ready: target={target.target_id} gateway={url}")


def reconcile_up_target(
    target: DeploymentTarget,
    *,
    main_profile: str | None,
    main_base_url: str | None,
    access_profile: str | None,
    confirm_access: bool,
) -> None:
    configured = setup_target(
        target,
        main_profile,
        main_base_url,
        access_profile,
        confirm_access,
    )
    if not configured:
        raise RuntimeError(
            "configuration change requires confirmation; platform was not started"
        )

    values = _env_values()
    if values.get("BUILD_PROFILE") != "local":
        ensure_target_artifacts(target)
        prepare_target(target)
    up_target(target)


def down_target(target: DeploymentTarget) -> None:
    values = _env_values()
    if values.get("BUILD_PROFILE") == "local":
        _run_step("Stopping application services", "bash", "scripts/ops/down_services.sh", "--local")
        print("[platform] stopped: app-only")
        return
    compose_error: subprocess.CalledProcessError | None = None
    try:
        if target.control_mode == "static":
            process_env = {**os.environ, "DEPLOYMENT_TARGET": target.target_id}
            _run_step(
                "Stopping platform services",
                "bash",
                "scripts/compose/static_main_compose.sh",
                "down",
                env=process_env,
            )
        else:
            _run_step("Stopping platform services", "bash", "scripts/ops/down_services.sh", "--compose")
    except subprocess.CalledProcessError as exc:
        compose_error = exc
    finally:
        if target.runtime_backend == "mlx-vlm":
            _run_step(
                "Stopping Metal Main Model runtime",
                sys.executable,
                "scripts/runtime/macos_mlx_runtime.py",
                "stop",
            )
    if compose_error is not None:
        raise compose_error
    print(f"[platform] stopped: target={target.target_id}")


def _gateway_json(
    values: dict[str, str],
    path: str,
    *,
    admin: bool = False,
) -> tuple[int, dict[str, object] | None]:
    host = values.get("GATEWAY_BIND_ADDR") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    services = load_yaml_mapping(SERVICES_PATH).get("services", {})
    gateway = services.get("gateway") if isinstance(services, dict) else None
    if not isinstance(gateway, dict) or "default_host_port" not in gateway:
        return 0, None
    port = values.get("GATEWAY_PORT") or str(gateway["default_host_port"])
    request = urllib.request.Request(f"http://{host}:{port}{path}")
    if admin:
        token = values.get("ADMIN_API_KEY") or values.get("ADMIN_API_KEYS", "").split(",", 1)[0]
        if token:
            request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = response.read().decode("utf-8")
            doc = json.loads(payload)
            return response.status, doc if isinstance(doc, dict) else None
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            doc = None
        return exc.code, doc if isinstance(doc, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return 0, None


def status_target(target: DeploymentTarget) -> int:
    values = _env_values()
    if values.get("BUILD_PROFILE") == "local":
        process_status = subprocess.run(
            ["bash", "scripts/ops/status_services.sh", "--local"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        url, gateway_ready = _gateway_probe(values, "/health")
        ready = process_status.returncode == 0 and gateway_ready
        print(f"Platform      {'READY' if ready else 'DEGRADED'}")
        print(f"Target        {target.target_id}")
        print(f"Access        {values.get('ACCESS_PROFILE') or 'legacy/custom'}")
        print(f"Gateway       {'READY' if gateway_ready else 'UNAVAILABLE'}")
        print(f"Applications  {'READY' if process_status.returncode == 0 else 'DEGRADED'}")
        if not ready:
            print("")
            print("Attention")
            print("  - one or more app-only processes are unavailable")
            print("")
            print("Next")
            print("  make logs")
            return 1
        return 0

    code, ready = _gateway_json(values, "/ready", admin=True)
    ready_status = ready.get("status") if isinstance(ready, dict) else None
    platform_status = "READY" if code == 200 and ready_status == "ready" else "DEGRADED"

    print(f"Platform      {platform_status}")
    print(f"Target        {target.target_id}")
    access = values.get("ACCESS_PROFILE") or "legacy/custom"
    print(f"Access        {access}")
    print(f"Gateway       {'READY' if code == 200 else 'UNAVAILABLE'}")

    if values.get("BUILD_PROFILE") != "local" and code:
        runtime_code, runtime_doc = _gateway_json(values, "/admin/runtimes", admin=True)
        if runtime_code == 200 and isinstance(runtime_doc, dict):
            runtimes = runtime_doc.get("runtimes")
            if isinstance(runtimes, list):
                print("")
                print("Runtimes")
                for item in runtimes:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("service_key") or "unknown")
                    state = str(item.get("state") or "unknown").upper()
                    container = str(item.get("container_status") or "")
                    suffix = f" / {container}" if container else ""
                    print(f"  {key:<28} {state}{suffix}")
            topology = runtime_doc.get("topology")
            if isinstance(topology, list):
                unavailable = [
                    str(item.get("service_key"))
                    for item in topology
                    if isinstance(item, dict) and item.get("available") is False
                ]
                for key in unavailable:
                    print(f"  {key:<28} UNAVAILABLE / policy")

    attention: list[str] = []
    if isinstance(ready, dict):
        deps = ready.get("dependencies")
        if isinstance(deps, list):
            for item in deps:
                if not isinstance(item, dict) or item.get("status") == "ready":
                    continue
                name = item.get("name")
                detail = item.get("message") or item.get("status")
                attention.append(f"{name}: {detail}")
    if code == 0:
        attention.append("Gateway is not reachable")
    elif code not in (200, 503):
        attention.append(f"Gateway readiness returned HTTP {code}")

    if attention:
        print("")
        print("Attention")
        for item in attention:
            print(f"  - {item}")
        print("")
        print("Next")
        print("  make logs")
        return 1
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operator-facing local platform lifecycle")
    parser.add_argument(
        "action",
        choices=("up", "down", "status"),
    )
    parser.add_argument("--target")
    parser.add_argument("--main-profile")
    parser.add_argument("--main-base-url")
    parser.add_argument("--access-profile", choices=access_profile_names())
    parser.add_argument("--confirm-access", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.confirm_access and not args.access_profile:
            raise RuntimeError("CONFIRM=access requires ACCESS=local|private|edge")
        if args.action != "up" and (
            args.main_profile or args.main_base_url or args.access_profile or args.confirm_access
        ):
            raise RuntimeError("MODEL, MAIN_URL, ACCESS and CONFIRM are make up options")

        if args.action == "down" and not ENV_PATH.is_file():
            _run_step(
                "Stopping checkout-owned resources",
                "bash",
                "scripts/ops/down_all.sh",
            )
            print("[platform] stopped: checkout-owned resources")
            return 0

        target = _target(args.target, require_env=args.action != "up")
        if args.action == "up":
            reconcile_up_target(
                target,
                main_profile=args.main_profile,
                main_base_url=args.main_base_url,
                access_profile=args.access_profile,
                confirm_access=args.confirm_access,
            )
        elif args.action == "down":
            down_target(target)
            _run_step(
                "Checking for checkout-owned leftovers",
                "bash",
                "scripts/ops/down_all.sh",
            )
        else:
            return status_target(target)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[platform] ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
