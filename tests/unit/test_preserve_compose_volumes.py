"""Upgrades preserve cache data and reject ambiguous volume ownership."""
import json
import subprocess
import shutil

import pytest

from scripts.compose import preserve_volumes as reuse
from scripts.ops.compose_ownership import CHECKOUT_LABEL, PROJECT_LABEL, WORKING_DIR_LABEL


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    volume = {
        "Name": "project_cache", "CreatedAt": "2026-10-01T00:00:00Z",
        "Driver": "local", "Options": None,
        "Labels": {PROJECT_LABEL: "project", "com.docker.compose.volume": "cache"},
    }
    users = {"old": {"Config": {"Labels": {WORKING_DIR_LABEL: str(root / "ops/compose")}}}}

    def docker(*args):
        if args == ("volume", "ls", "-q"):
            return volume["Name"]
        if args[:2] == ("volume", "inspect"):
            return json.dumps([volume])
        if args[0] == "ps":
            return "\n".join(users)
        if args[:2] == ("container", "inspect"):
            return json.dumps([users[args[2]]])
        raise AssertionError(f"Unexpected Docker mutation: {args}")

    monkeypatch.setattr(reuse, "docker", docker)
    config = {"volumes": {"cache": {"name": "project_cache", "labels": {CHECKOUT_LABEL: str(root)}}}}
    return root, volume, users, config


def test_verified_legacy_cache_survives_label_upgrade_and_down_up(inventory):
    root, volume, users, config = inventory
    before = json.dumps(volume)
    path = reuse.preserve_volumes(root, "project", config)
    assert '!override {"name": "project_cache", "external": true}' in path.read_text()
    assert json.dumps(volume) == before  # no volume delete, recreate, or relabel
    users.clear()  # ordinary down removes the containers, not the volume
    assert reuse.preserve_volumes(root, "project", config).read_bytes() == path.read_bytes()


def test_unverified_legacy_orphan_is_rejected_without_manifest(inventory):
    root, _, users, config = inventory
    users.clear()
    with pytest.raises(RuntimeError, match="ownership cannot be verified"):
        reuse.preserve_volumes(root, "project", config)
    assert not list((root / ".runtime/compose-state").glob("*.json"))


def test_replaced_orphan_does_not_inherit_old_manifest_identity(inventory):
    root, volume, users, config = inventory
    reuse.preserve_volumes(root, "project", config)
    users.clear()
    volume["CreatedAt"] = "2026-10-21T00:00:00Z"
    with pytest.raises(RuntimeError, match="ownership cannot be verified"):
        reuse.preserve_volumes(root, "project", config)


def test_copying_runtime_state_to_another_checkout_cannot_adopt_legacy_orphans(inventory):
    root, _, users, config = inventory
    reuse.preserve_volumes(root, "project", config)
    clone = root.with_name("clone")
    shutil.copytree(root, clone)
    users.clear()
    with pytest.raises(RuntimeError, match="ownership cannot be verified"):
        reuse.preserve_volumes(clone, "project", config)


@pytest.mark.parametrize("foreign_owner", [False, True])
def test_volume_cannot_cross_checkout_boundaries(inventory, foreign_owner):
    root, volume, users, config = inventory
    if foreign_owner:
        volume["Labels"][CHECKOUT_LABEL] = str(root.with_name("other"))
    else:
        users["foreign"] = {"Config": {"Labels": {WORKING_DIR_LABEL: str(root.with_name("repo-other"))}}}
    with pytest.raises(RuntimeError, match="another checkout|outside this checkout"):
        reuse.preserve_volumes(root, "project", config)


def test_current_checkout_label_proves_orphan_ownership(inventory):
    root, volume, users, config = inventory
    volume["Labels"][CHECKOUT_LABEL] = str(root)
    users.clear()
    assert reuse.preserve_volumes(root, "project", config).exists()


def test_changed_driver_options_require_explicit_migration(inventory):
    root, _, _, config = inventory
    config["volumes"]["cache"]["driver_opts"] = {"type": "tmpfs"}
    with pytest.raises(RuntimeError, match="explicit migration"):
        reuse.preserve_volumes(root, "project", config)


def test_removing_driver_options_does_not_silently_reuse_old_storage(inventory):
    root, volume, _, config = inventory
    volume["Options"] = {"type": "tmpfs"}
    with pytest.raises(RuntimeError, match="explicit migration"):
        reuse.preserve_volumes(root, "project", config)


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker Compose unavailable")
def test_override_merges_as_external_without_incompatible_labels(inventory, tmp_path):
    root, _, _, config = inventory
    override = reuse.preserve_volumes(root, "project", config)
    source = tmp_path / "compose.json"
    source.write_text(json.dumps({**config, "services": {"test": {"image": "unused", "volumes": ["cache:/cache"]}}}))
    result = subprocess.run(["docker", "compose", "-f", str(source), "-f", str(override),
                             "config", "--format", "json"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["volumes"]["cache"] == {"name": "project_cache", "external": True}
