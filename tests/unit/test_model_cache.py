"""prepare_model_snapshot의 exact-revision cache reuse/download 계약을 검증한다."""

from __future__ import annotations

from pathlib import Path

import huggingface_hub

from ai_model_serving.main_model.cache import PreparedModelSnapshot, prepare_model_snapshot


def test_prepare_reuses_exact_revision_from_local_cache(
    tmp_path, monkeypatch
):
    snapshot = tmp_path / "models--org--model" / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    calls: list[dict] = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        return str(snapshot)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    result = prepare_model_snapshot(
        model_id="org/model",
        revision="a" * 40,
        cache_dir=tmp_path,
        token="secret",
    )

    assert result.snapshot_path == snapshot
    assert [call.get("local_files_only", False) for call in calls] == [True, True]
    assert all(call["revision"] == "a" * 40 for call in calls)
    assert all(call["repo_id"] == "org/model" for call in calls)


def test_prepare_downloads_only_after_exact_revision_cache_miss(
    tmp_path, monkeypatch
):
    snapshot = tmp_path / "models--org--model" / "snapshots" / ("b" * 40)
    snapshot.mkdir(parents=True)
    calls: list[dict] = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise FileNotFoundError("snapshot is not cached")
        return str(snapshot)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    result = prepare_model_snapshot(
        model_id="org/model",
        revision="b" * 40,
        cache_dir=tmp_path,
        token="secret",
    )

    assert result.snapshot_path == snapshot
    assert [call.get("local_files_only", False) for call in calls] == [True, False, True]
    assert all(call["revision"] == "b" * 40 for call in calls)


def test_cache_cli_reads_profile_metadata_without_runtime_image_env(tmp_path, monkeypatch):
    """HF cache 준비는 Docker image digest가 아니라 pinned model revision만 소비한다."""
    from ai_model_serving.main_model import cache_cli

    monkeypatch.delenv("VLLM_IMAGE", raising=False)
    monkeypatch.delenv("MAIN_MODEL_VLLM_IMAGE_OVERRIDE", raising=False)
    def fake_prepare(**kwargs):
        return PreparedModelSnapshot(
            model_id=kwargs["model_id"],
            revision=kwargs["revision"],
            snapshot_path=tmp_path,
        )

    monkeypatch.setattr(cache_cli, "prepare_model_snapshot", fake_prepare)
    root = Path(__file__).resolve().parents[2]

    assert cache_cli.main(
        [
            "--profile",
            "gemma4-12b-unified-fp8",
            "--catalog",
            str(root / "configs/main_model_profiles.yaml"),
            "--cache-dir",
            str(tmp_path),
        ]
    ) == 0
