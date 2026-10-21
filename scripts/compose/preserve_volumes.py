"""Reuse verified existing volumes without Compose's destructive recreate prompt."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.atomic_file import atomic_write  # noqa: E402
from scripts.ops.compose_ownership import CHECKOUT_LABEL, PROJECT_LABEL, docker, owns_container  # noqa: E402


def volume_identity(document: dict) -> dict:
    return {key: document.get(key) for key in ("Name", "CreatedAt", "Driver", "Options", "Labels")}


def preserve_volumes(root: Path, project: str, config: dict) -> Path:
    root = root.resolve()
    state = root / ".runtime/compose-state"
    state.mkdir(parents=True, exist_ok=True)
    suffix = hashlib.sha256(project.encode()).hexdigest()[:16]
    manifest = state / f"volume-reuse-{suffix}.json"
    prior = json.loads(manifest.read_text()) if manifest.exists() else {}
    if not isinstance(prior, dict):
        raise RuntimeError(f"invalid volume reuse manifest: {manifest}")
    recorded = prior.get("volumes", {}) if prior.get("checkout") == str(root) else {}
    if not isinstance(recorded, dict):
        raise RuntimeError(f"invalid volume reuse manifest: {manifest}")
    existing = set(docker("volume", "ls", "-q").splitlines())
    reused = {}
    updated = dict(recorded)
    for key, spec in (config.get("volumes") or {}).items():
        if spec.get("external"):
            continue
        name = spec["name"]
        if name not in existing:
            continue
        document = json.loads(docker("volume", "inspect", name))[0]
        labels = document.get("Labels") or {}
        owner = labels.get(CHECKOUT_LABEL)
        if owner and owner != str(root):
            raise RuntimeError(f"volume {name} belongs to another checkout; preserved")
        for setting, expected, actual in (
            ("driver", spec.get("driver") or "local", document.get("Driver")),
            ("driver_opts", spec.get("driver_opts") or {}, document.get("Options") or {}),
        ):
            if expected != actual:
                raise RuntimeError(f"volume {name}: {setting} changed; explicit migration required")
        users = docker("ps", "-aq", "--filter", f"volume={name}").split()
        for container in users:
            if not owns_container(root, json.loads(docker("container", "inspect", container))[0]):
                raise RuntimeError(f"volume {name} is attached outside this checkout; preserved")
        identity = volume_identity(document)
        verified_attachment = (
            bool(users) and labels.get(PROJECT_LABEL) == project
            and labels.get("com.docker.compose.volume") == key
        )
        if not (owner == str(root) or verified_attachment or recorded.get(name) == identity):
            raise RuntimeError(
                f"volume {name}: checkout ownership cannot be verified; preserved. "
                "Do not accept Compose's recreate prompt or delete this volume."
            )
        updated[name] = identity
        reused[key] = {"name": name, "external": True}

    # !override discards labels/driver fields, which external volumes must not carry.
    # The local manifest retains attachment evidence across an ordinary down/up.
    lines = ["volumes:"] if reused else ["{}"]
    for key, spec in reused.items():
        lines.append(f"  {json.dumps(key)}: !override {json.dumps(spec)}")
    output = state / f"volume-reuse-{suffix}.yaml"
    atomic_write(manifest, (json.dumps({"checkout": str(root), "volumes": updated}, indent=2) + "\n").encode())
    atomic_write(output, ("\n".join(lines) + "\n").encode())
    if reused:
        print(f"[compose] preserving existing volumes: {', '.join(reused)}", file=sys.stderr)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    args = parser.parse_args()
    try:
        command = ["compose", "--project-name", args.project]
        for path in args.compose_file:
            command += ["-f", path]
        command += ["--env-file", args.env_file, "config", "--format", "json"]
        config = json.loads(docker(*command))
        print(preserve_volumes(args.root, args.project, config))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"[compose] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
