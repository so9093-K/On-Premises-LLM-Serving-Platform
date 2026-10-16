"""Main Model Profile에 사용할 고정된 Hugging Face Snapshot을 준비한다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreparedModelSnapshot:
    model_id: str
    revision: str
    snapshot_path: Path


def default_hf_hub_cache_dir() -> Path:
    """Hugging Face Hub와 vLLM이 공유하는 캐시 루트를 반환한다."""
    explicit = os.environ.get("HF_HUB_CACHE")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HF_HOME", "/root/.cache/huggingface")) / "hub"


def prepare_model_snapshot(
    *,
    model_id: str,
    revision: str,
    cache_dir: Path,
    token: str | None = None,
) -> PreparedModelSnapshot:
    """Hugging Face Hub 캐시에서 정확히 지정한 Revision을 재사용하거나 내려받는다.

    다운로드 후 로컬 Snapshot을 다시 열어 검증한다. ``cache_dir``는 보통
    ``HF_HOME/hub``이며 ``HF_HOME`` 자체가 아니다. 이 경계를 명시해야
    모델 준비 단계와 vLLM이 서로 다른 ``models--*`` 캐시 트리를 만들지 않는다.
    """
    from huggingface_hub import snapshot_download

    cache_dir.mkdir(parents=True, exist_ok=True)
    resolved_token = token or os.environ.get("HF_TOKEN") or os.environ.get(
        "HUGGING_FACE_HUB_TOKEN"
    )
    try:
        downloaded = Path(
            snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=str(cache_dir),
                token=resolved_token or None,
                local_files_only=True,
            )
        )
    except Exception:
        downloaded = Path(
            snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=str(cache_dir),
                token=resolved_token or None,
            )
        )
    verified = Path(
        snapshot_download(
            repo_id=model_id,
            revision=revision,
            cache_dir=str(cache_dir),
            token=resolved_token or None,
            local_files_only=True,
        )
    )
    if downloaded.resolve() != verified.resolve():
        raise RuntimeError(
            "Hugging Face cache verification resolved a different snapshot path"
        )
    if not verified.is_dir():
        raise RuntimeError(f"prepared Hugging Face snapshot is missing: {verified}")
    return PreparedModelSnapshot(model_id, revision, verified)
