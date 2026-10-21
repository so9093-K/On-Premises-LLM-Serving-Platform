"""Checkout ownership for Docker discovery and cleanup; standard library only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

CHECKOUT_LABEL = "ai_model_serving.checkout"
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
PROJECT_LABEL = "com.docker.compose.project"


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"docker {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def owns_container(root: Path, document: dict) -> bool:
    directory = (document.get("Config", {}).get("Labels") or {}).get(WORKING_DIR_LABEL)
    return bool(directory) and Path(directory).resolve() in {
        root.resolve(), (root / "ops/compose").resolve(),
    }


def owned_container_ids(root: Path, service: str | None = None) -> list[str]:
    containers: list[str] = []
    for directory in (root.resolve(), (root / "ops/compose").resolve()):
        args = ["ps", "-aq", "--filter", f"label={WORKING_DIR_LABEL}={directory}"]
        if service:
            args += ["--filter", f"label=com.docker.compose.service={service}"]
        containers.extend(docker(*args).split())
    return list(dict.fromkeys(containers))


def assert_project_owned(root: Path, project: str) -> None:
    for container in docker("ps", "-aq", "--filter", f"label={PROJECT_LABEL}={project}").split():
        document = json.loads(docker("container", "inspect", container))[0]
        if not owns_container(root, document):
            raise RuntimeError(
                f"refusing to mutate project '{project}': container {container} belongs "
                "to another checkout or has no verifiable owner"
            )
    for kind in ("network", "volume"):
        for resource in docker(kind, "ls", "-q", "--filter", f"label={PROJECT_LABEL}={project}").split():
            document = json.loads(docker(kind, "inspect", resource))[0]
            owner = (document.get("Labels") or {}).get(CHECKOUT_LABEL)
            if owner and owner != str(root.resolve()):
                raise RuntimeError(f"refusing to mutate project '{project}': {kind} {resource} belongs to another checkout")


def owned_resources(root: Path, kind: str) -> list[str]:
    return docker(kind, "ls", "-q", "--filter", f"label={CHECKOUT_LABEL}={root.resolve()}").split()


def resource_document(root: Path, kind: str, resource: str) -> dict:
    document = json.loads(docker(kind, "inspect", resource))[0]
    labels = (document.get("Config", {}).get("Labels") if kind == "image" else document.get("Labels")) or {}
    if labels.get(CHECKOUT_LABEL) != str(root.resolve()):
        raise RuntimeError(f"refusing to remove {kind} {resource}: checkout ownership changed")
    return document


def down(root: Path) -> None:
    containers = owned_container_ids(root)
    # Recheck every container before the first mutation, including stopped ones.
    for container in containers:
        if not owns_container(root, json.loads(docker("container", "inspect", container))[0]):
            raise RuntimeError(f"refusing to stop container {container}: checkout ownership changed")
    if containers:
        docker("stop", *containers)
        docker("rm", *containers)
    for network in owned_resources(root, "network"):
        document = resource_document(root, "network", network)
        if document.get("Containers"):
            raise RuntimeError(f"network {network} is still in use; preserved")
        docker("network", "rm", network)
    print("[down-all] checkout-owned containers/networks stopped; unlabeled resources preserved")


def purge_artifacts(root: Path) -> None:
    # A Compose project name alone never proves ownership of an orphaned volume.
    for volume in owned_resources(root, "volume"):
        resource_document(root, "volume", volume)
        if docker("ps", "-aq", "--filter", f"volume={volume}"):
            raise RuntimeError(f"volume {volume} is still in use; preserved")
        docker("volume", "rm", volume)
    for image in sorted(set(owned_resources(root, "image"))):
        resource_document(root, "image", image)
        if docker("ps", "-aq", "--filter", f"ancestor={image}"):
            print(f"[purge] image {image} is still in use; preserved")
            continue
        docker("image", "rm", image)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    subparsers = parser.add_subparsers(dest="action", required=True)
    guard = subparsers.add_parser("assert-project")
    guard.add_argument("--project", required=True)
    subparsers.add_parser("down")
    subparsers.add_parser("purge-artifacts")
    args = parser.parse_args(argv)
    try:
        if args.action == "assert-project":
            assert_project_owned(args.root, args.project)
        elif args.action == "down":
            down(args.root)
        else:
            purge_artifacts(args.root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[ownership] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
