"""빌드 입력의 내용 해시와 선택적인 Git 출처를 공통으로 조회한다."""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Docker COPY 입력과 해당 이미지의 빌드 제어 파일을 한곳에서 소유한다.
_DISTRIBUTION_INPUTS = ("LICENSE", "NOTICE")
_SHARED_CONTROLS = (
    ".dockerignore", "scripts/lib/source_provenance.py",
    "scripts/lib/source_provenance.sh", "scripts/lib/project_image_ownership.sh",
)
ARTIFACT_INPUTS = {
    "platform": (
        "Dockerfile", "pyproject.toml", "uv.lock", "VERSION", "src", "configs", "specs/schemas",
        "scripts/build/build_platform_image.sh", "scripts/build/smoke_platform_image.sh",
        *_SHARED_CONTROLS,
    ),
    "vllm-unified": (
        "ops/images/vllm-unified/Dockerfile",
        "ops/images/vllm-unified/requirements.bnb.lock",
        "ops/images/vllm-unified/requirements.media.lock",
        "ops/patches/apply_gemma4_multimodal_patches.py",
        "ops/patches/apply_gemma4_streaming_reasoning_patch.py",
        "ops/patches/transformers_llama_head_dim_guard.py",
        "configs/vllm_unified_build.yaml",
        "scripts/build/build_vllm_unified_image.sh",
        "scripts/models/print_vllm_unified_compatibility.py",
        "scripts/lib/vllm_unified_image.sh", "scripts/lib/image_ref_policy.sh",
        *_SHARED_CONTROLS,
    ),
}


def input_paths(artifact: str, *, distribution: bool = False) -> tuple[str, ...]:
    paths = ARTIFACT_INPUTS[artifact]
    if distribution:
        paths += _DISTRIBUTION_INPUTS
        if artifact == "platform":
            paths += ("README.md",)
        else:
            paths += ("VERSION",)
    return paths


@dataclass(frozen=True)
class SourceProvenance:
    revision: str
    state: str
    digest: str
    runtime_digest: str


def _excluded(path: Path) -> bool:
    return (path.name in {"__pycache__", "node_modules", ".git", ".venv",
                          ".runtime", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
            or path.name.endswith((".egg-info", ".pyc", ".secret", ".pem", ".key"))
            or path.name.startswith(".env"))


def _content_digest(root: Path, artifact: str, *, distribution: bool) -> str:
    """상대 경로·내용으로 식별하며 배치 경로·Git·로컬 secret은 포함하지 않는다."""
    paths: list[Path] = []

    def on_error(error: OSError) -> None:
        raise error

    for name in input_paths(artifact, distribution=distribution):
        path = root / name
        if path.is_symlink() or path.is_file():
            paths.append(path)
        elif path.is_dir():
            for parent, directories, files in os.walk(path, onerror=on_error, followlinks=False):
                for directory in list(directories):
                    child = Path(parent) / directory
                    if _excluded(child):
                        directories.remove(directory)
                    elif child.is_symlink():
                        paths.append(child)
                        directories.remove(directory)
                paths.extend(Path(parent) / filename for filename in files if not _excluded(Path(filename)))
    digest = hashlib.sha256(f"image-inputs-v2:{artifact}\0".encode("ascii"))
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode("utf-8") + b"\0")
        elif path.is_file():
            digest.update(b"file\0" + str(path.stat().st_mode & 0o111).encode("ascii") + b"\0")
            content = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content.update(chunk)
            digest.update(content.digest())
        else:
            raise ValueError(f"일반 파일이 아닌 빌드 입력입니다: {path}")
    # 이미지 태그·캐시·체크아웃 경로는 실행 입력이 아니다. 실제 build override만 포함한다.
    overrides = ("PLATFORM_BUILD_PLATFORM",) if artifact == "platform" else ("VLLM_BASE_IMAGE",)
    for name in overrides:
        digest.update(name.encode("ascii") + b"\0" + os.environ.get(name, "").encode("utf-8") + b"\0")
    return "sha256:" + digest.hexdigest()


def source_digest(root: Path, artifact: str = "platform") -> str:
    """배포물에 포함된 문서·라이선스까지 기록하는 빌드 출처다."""
    return _content_digest(root, artifact, distribution=True)


def runtime_digest(root: Path, artifact: str = "platform") -> str:
    """기동 시 재사용 판단에는 실행 입력만 읽으며 Git·문서를 조회하지 않는다."""
    return _content_digest(root, artifact, distribution=False)


def git_metadata(root: Path) -> tuple[str, str]:
    """Git 미설치·소유권 거부를 실행 실패로 취급하지 않는다."""
    try:
        if not (root / ".git").exists():
            return "", "local"
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                  capture_output=True, check=False, timeout=10)
        if revision.returncode != 0 or not revision.stdout.strip():
            return "", "local"
        state = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                               text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "", "local"
    if revision.returncode != 0 or state.returncode != 0 or not revision.stdout.strip():
        return "", "local"
    return revision.stdout.strip(), "dirty" if state.stdout.strip() else "clean"


def read_source_provenance(root: Path, artifact: str = "platform") -> SourceProvenance:
    revision, state = git_metadata(root)
    return SourceProvenance(revision, state, source_digest(root, artifact), runtime_digest(root, artifact))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="이미지별 실행 입력과 배포 출처를 조회합니다.")
    parser.add_argument("--artifact", choices=tuple(ARTIFACT_INPUTS), default="platform")
    parser.add_argument("--input-paths", action="store_true")
    args = parser.parse_args(argv or [])
    if args.input_paths:
        print(*input_paths(args.artifact, distribution=True), sep="\n")
        return 0
    try:
        source = read_source_provenance(ROOT, args.artifact)
    except (OSError, ValueError) as exc:
        print(f"[image] 소스 파일 확인 실패: {exc}. 파일 형식과 읽기 권한을 확인하세요.", file=sys.stderr)
        return 2
    print(source.revision or "local", source.state, source.digest, source.runtime_digest, sep="\t")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
