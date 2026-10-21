"""Destructive cleanup must not cross checkout boundaries, even for orphaned resources."""
from __future__ import annotations

import json

import pytest

from scripts.ops import compose_ownership as ownership


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    resources = {kind: {} for kind in ("container", "network", "volume", "image")}
    mutations = []

    def docker(*args):
        kind = "container" if args[0] == "ps" else args[0]
        if args[0] == "ps" or args[1] == "ls":
            filters = [args[i + 1] for i, word in enumerate(args) if word == "--filter"]
            found = []
            for key, doc in resources[kind].items():
                labels = (doc.get("Config", {}).get("Labels") if kind in {"image", "container"} else doc.get("Labels")) or {}
                for value in filters:
                    if value.startswith("label="):
                        label, expected = value[6:].split("=", 1)
                        if labels.get(label) != expected:
                            break
                    elif value.startswith("volume=") and value[7:] not in doc.get("volumes", []):
                        break
                    elif value.startswith("ancestor=") and value[9:] != doc.get("Image"):
                        break
                else:
                    found.append(key)
            return "\n".join(found)
        if args[1] == "inspect":
            return json.dumps([resources[kind][args[2]]])
        mutations.append(args)
        if args[0] == "rm":
            for key in args[1:]:
                del resources["container"][key]
        elif args[1] == "rm":
            for key in args[2:]:
                resources[kind].pop(key, None)
        return ""

    monkeypatch.setattr(ownership, "docker", docker)
    return root, resources, mutations


def container(directory=None, **extra):
    labels = {ownership.PROJECT_LABEL: "same-project"}
    if directory is not None:
        labels[ownership.WORKING_DIR_LABEL] = str(directory)
    return {"Config": {"Labels": labels}, **extra}


def labeled(root):
    return {"Labels": {ownership.CHECKOUT_LABEL: str(root), ownership.PROJECT_LABEL: "same-project"}}


def test_down_finds_both_directories_and_preserves_same_project_foreign_checkout(inventory):
    root, resources, mutations = inventory
    resources["container"].update({
        "canonical": container(root / "ops/compose"),
        "legacy": container(root),
        "foreign": container(root.with_name("repo-backup") / "ops/compose"),
        "unknown": container(),
    })
    resources["network"].update({
        "own-net": labeled(root), "foreign-net": labeled(root.with_name("other")),
        "legacy-net": {"Labels": {ownership.PROJECT_LABEL: "same-project"}},
    })

    ownership.down(root)

    assert set(resources["container"]) == {"foreign", "unknown"}
    assert set(resources["network"]) == {"foreign-net", "legacy-net"}
    assert mutations[0] == ("stop", "legacy", "canonical")


@pytest.mark.parametrize("owner", ["foreign", "unknown"])
def test_compose_mutations_reject_ambiguous_project_before_mutation(inventory, owner):
    root, resources, mutations = inventory
    resources["container"]["own"] = container(root)
    resources["container"]["other"] = container(root.with_name("other") if owner == "foreign" else None)
    with pytest.raises(RuntimeError, match="refusing to mutate"):
        ownership.assert_project_owned(root, "same-project")
    assert mutations == []


def test_project_guard_accepts_canonical_and_legacy_checkout(inventory):
    root, resources, mutations = inventory
    resources["container"].update({"old": container(root), "new": container(root / "ops/compose")})
    ownership.assert_project_owned(root, "same-project")
    assert mutations == []


def test_project_guard_rejects_active_legacy_network_before_partial_startup(inventory):
    root, resources, mutations = inventory
    resources["container"]["own"] = container(root)
    resources["network"]["legacy"] = {
        "Labels": {ownership.PROJECT_LABEL: "same-project"}, "Containers": {"own": {}},
    }
    with pytest.raises(RuntimeError, match="run make down, then make up"):
        ownership.assert_project_owned(root, "same-project")
    assert mutations == []
    resources["network"]["legacy"]["Containers"] = {}
    ownership.assert_project_owned(root, "same-project")
    assert mutations == []


def test_purge_only_removes_labeled_orphans_and_preserves_images_used_elsewhere(inventory):
    root, resources, mutations = inventory
    resources["volume"].update({
        "own": labeled(root), "foreign": labeled(root.with_name("other")),
        "orphan": {"Labels": {ownership.PROJECT_LABEL: "same-project"}},
    })
    resources["image"].update({
        "own-image": {"Config": labeled(root), "RepoTags": ["mutable:tag"]},
        "shared-image": {"Config": labeled(root)},
        "legacy-image": {"RepoTags": ["ai-model-serving-platform:0.0.1"]},
    })
    resources["container"]["foreign"] = container(root.with_name("other"), Image="shared-image")

    ownership.purge_artifacts(root)

    assert set(resources["volume"]) == {"foreign", "orphan"}
    assert set(resources["image"]) == {"legacy-image", "shared-image"}
    assert ("volume", "rm", "own") in mutations
    assert ("image", "rm", "own-image") in mutations


def test_purge_refuses_volume_in_use_by_foreign_checkout(inventory):
    root, resources, mutations = inventory
    resources["volume"]["shared"] = labeled(root)
    resources["container"]["foreign"] = container(root.with_name("other"), volumes=["shared"])
    with pytest.raises(RuntimeError, match="still in use"):
        ownership.purge_artifacts(root)
    assert mutations == []


def test_docker_inventory_failure_is_not_treated_as_empty(monkeypatch, tmp_path):
    def fail(*args):
        raise RuntimeError("daemon unavailable")
    monkeypatch.setattr(ownership, "docker", fail)
    with pytest.raises(RuntimeError, match="daemon unavailable"):
        ownership.down(tmp_path)


@pytest.mark.parametrize("kind", ["network", "volume"])
def test_compose_guard_rejects_foreign_orphans_even_without_containers(inventory, kind):
    root, resources, mutations = inventory
    resources[kind]["foreign-orphan"] = labeled(root.with_name("other"))
    with pytest.raises(RuntimeError, match="another checkout"):
        ownership.assert_project_owned(root, "same-project")
    assert mutations == []


def test_purge_rechecks_owner_after_discovery(inventory, monkeypatch):
    root, resources, mutations = inventory
    resources["volume"]["changed-owner"] = labeled(root.with_name("other"))
    monkeypatch.setattr(ownership, "owned_resources", lambda root, kind: ["changed-owner"])
    with pytest.raises(RuntimeError, match="ownership changed"):
        ownership.purge_artifacts(root)
    assert mutations == []
