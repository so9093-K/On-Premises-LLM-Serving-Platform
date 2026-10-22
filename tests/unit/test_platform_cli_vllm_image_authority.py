from __future__ import annotations

from scripts import platform_cli


def test_local_build_uses_shared_vllm_image_authority(monkeypatch):
    local_id = "sha256:" + "a" * 64
    new_id = "sha256:" + "b" * 64
    platform_digest = "registry.example.com/platform@sha256:" + "d" * 64
    commands: list[tuple[tuple[str, ...], dict[str, str] | None]] = []
    pinned: list[tuple[str, str]] = []

    monkeypatch.setattr(
        platform_cli,
        "_env_values",
        lambda: {
            "PLATFORM_IMAGE": platform_digest,
            "VLLM_IMAGE": local_id,
        },
    )
    monkeypatch.setattr(
        platform_cli,
        "_run_step",
        lambda _label, *command, env=None: commands.append((command, env)),
    )
    monkeypatch.setattr(platform_cli, "resolve_local_image_id", lambda image: new_id)
    monkeypatch.setattr(
        platform_cli,
        "pin_matching_env_values",
        lambda _path, source, image_id, **_kwargs: pinned.append((source, image_id)) or ["VLLM_IMAGE"],
    )
    target = type("Target", (), {"controllable": True, "target_id": "linux-nvidia-dynamic"})()

    platform_cli.build_target(target, no_cache=True)

    assert len(commands) == 1
    assert commands[0][0] == ("bash", "scripts/build/build_vllm_unified_image.sh")
    assert commands[0][1] is not None
    assert commands[0][1]["PROJECT_BUILD_NO_CACHE"] == "1"
    assert commands[0][1]["VLLM_UNIFIED_BUILD_IMAGE"].startswith("ai-model-serving-vllm-unified:")
    assert pinned == [(local_id, new_id)]


def test_artifact_checks_rebuild_only_stale_images(monkeypatch):
    """Platform 변경은 큰 vLLM 이미지 빌드를 함께 실행하지 않는다."""
    target = type("Target", (), {"controllable": True, "target_id": "linux-nvidia-dynamic"})()
    monkeypatch.setattr(platform_cli, "_env_values", lambda: {"PLATFORM_IMAGE": "platform:local", "VLLM_IMAGE": "vllm:local"})
    builds = []
    monkeypatch.setattr(platform_cli, "build_target", lambda target, **kwargs: builds.append(kwargs))
    for stale, expected in [
        (set(), []),
        ({"platform"}, [{"include_platform": True, "include_runtime": False}]),
        ({"vllm-unified"}, [{"include_platform": False, "include_runtime": True}]),
        ({"platform", "vllm-unified"}, [{"include_platform": True, "include_runtime": True}]),
    ]:
        builds.clear()
        monkeypatch.setattr(platform_cli, "_local_image_matches_source", lambda image, artifact: artifact not in stale)
        platform_cli.ensure_target_artifacts(target)
        assert builds == expected


def test_external_and_excluded_images_are_not_checked_or_rebuilt(monkeypatch):
    target = type("Target", (), {"controllable": True, "target_id": "linux-nvidia-dynamic"})()
    builds = []
    monkeypatch.setattr(platform_cli, "build_target", lambda target, **kwargs: builds.append(kwargs))
    monkeypatch.setattr(platform_cli, "_env_values", lambda: {
        "PLATFORM_IMAGE": "registry.example/platform@sha256:" + "a" * 64,
        "VLLM_IMAGE": "local:vllm",
    })
    monkeypatch.setattr(platform_cli, "_local_image_matches_source", lambda *args: False)
    platform_cli.ensure_target_artifacts(target, include_runtime=False)
    assert builds == []
    platform_cli.ensure_target_artifacts(target, include_platform=False)
    assert builds == [{"include_platform": False, "include_runtime": True}]
