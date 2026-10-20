#!/usr/bin/env python3
"""고정 Revision과 SHA-256으로 CPU GGUF Artifact를 준비한다."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "configs" / "cpu_model_artifact.yaml"
OUTPUT_ROOT = ROOT / ".runtime" / "cpu-models"


def _check_sha256(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def available_memory_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def prepare() -> Path:
    from huggingface_hub import hf_hub_download

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    model = manifest["model"]
    policy = manifest["runtime"]
    filename = str(model["filename"])
    revision = str(model["revision"])
    sha256 = str(model["sha256"]).lower()
    if Path(filename).name != filename or not filename.endswith(".gguf"):
        raise RuntimeError("CPU GGUF filename must be a single basename")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise RuntimeError("CPU model revision must be a full immutable SHA")
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise RuntimeError("CPU model checksum must be SHA-256")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / filename
    if output.is_file() and not output.is_symlink() and _check_sha256(output, sha256):
        print(f"[cpu-model] verified cached artifact: {output}")
        return output
    available = available_memory_mib()
    minimum_ram = int(policy["minimum_available_ram_mib"])
    if available is None or available < minimum_ram:
        raise RuntimeError(
            f"CPU RAM admission blocked: available={available}MiB, required={minimum_ram}MiB"
        )
    free = shutil.disk_usage(OUTPUT_ROOT).free // (1024 * 1024)
    minimum_disk = int(policy["minimum_free_disk_mib"])
    if free < minimum_disk:
        raise RuntimeError(
            f"CPU cache disk admission blocked: free={free}MiB, required={minimum_disk}MiB"
        )
    downloaded = Path(hf_hub_download(
        repo_id=str(model["repo_id"]),
        revision=revision,
        filename=filename,
        local_files_only=os.environ.get("CPU_MODEL_OFFLINE") == "1",
    ))
    if not _check_sha256(downloaded, sha256):
        raise RuntimeError("CPU model source checksum mismatch")
    descriptor, name = tempfile.mkstemp(prefix=".cpu-model.", suffix=".tmp", dir=OUTPUT_ROOT)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target, downloaded.open("rb") as src:
            shutil.copyfileobj(src, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if not _check_sha256(temporary, sha256):
            raise RuntimeError("CPU cache checksum verification failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"[cpu-model] verified: {output}")
    return output


def main() -> int:
    try:
        prepare()
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"[cpu-model] fail: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
