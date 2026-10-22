"""빌드 입력의 내용 해시와 선택적인 Git 출처를 공통으로 조회한다."""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 두 로컬 이미지의 Docker COPY 입력과 빌드 명령을 포함한다.
BUILD_INPUTS = (
    "Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "VERSION",
    "README.md", "LICENSE", "NOTICE", "src", "configs", "specs/schemas",
    "ops/images/vllm-unified", "ops/patches", "scripts",
)


@dataclass(frozen=True)
class SourceProvenance:
    revision: str
    state: str
    digest: str


def _excluded(path: Path) -> bool:
    return (path.name in {"__pycache__", "node_modules", ".git", ".venv",
                          ".runtime", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
            or path.name.endswith((".egg-info", ".pyc", ".secret", ".pem", ".key"))
            or path.name.startswith(".env"))


def source_digest(root: Path) -> str:
    """상대 경로·내용으로 식별하며 배치 경로·Git·로컬 secret은 포함하지 않는다."""
    paths: list[Path] = []

    def on_error(error: OSError) -> None:
        raise error

    for name in BUILD_INPUTS:
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
    digest = hashlib.sha256(b"platform-source-v1\0")
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
    return "sha256:" + digest.hexdigest()


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


def read_source_provenance(root: Path) -> SourceProvenance:
    revision, state = git_metadata(root)
    return SourceProvenance(revision, state, source_digest(root))


def main() -> int:
    import sys

    try:
        source = read_source_provenance(ROOT)
    except (OSError, ValueError) as exc:
        print(f"[image] 소스 파일 확인 실패: {exc}. 파일 형식과 읽기 권한을 확인하세요.", file=sys.stderr)
        return 2
    print(source.revision or "local", source.state, source.digest, sep="\t")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
