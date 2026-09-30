"""Access/host-boundary contract tests share the repository root helper."""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "VERSION").exists() and (parent / "configs").exists():
            return parent
    raise RuntimeError("repository root not found")


ROOT = _repo_root()
