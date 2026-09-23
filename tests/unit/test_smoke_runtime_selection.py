"""Smoke probe 대상이 현재 Runtime 상태를 따르는지 검증한다."""

from __future__ import annotations

import pytest

from scripts.runtime.smoke_runtime_selection import (
    SmokeRuntimeSelectionError,
    select_skipped_runtimes,
)


def runtime_document(*, embedding: str = "active", embedding_ko: str = "active"):
    return {
        "runtimes": [
            {"service_key": "embedding", "state": embedding},
            {"service_key": "embedding_ko", "state": embedding_ko},
        ],
        "topology": [
            {"service_key": "embedding", "available": True},
            {"service_key": "embedding_ko", "available": True},
            {"service_key": "prompt_injection_detector", "available": False},
        ],
    }


def test_stopped_runtime_is_skipped_but_active_runtime_remains_strict():
    document = runtime_document(embedding="stopped", embedding_ko="active")

    skipped = select_skipped_runtimes(
        document,
        ["embedding", "embedding_ko"],
    )

    assert skipped == ["embedding"]


def test_effective_topology_unavailable_runtime_is_skipped_without_state_record():
    document = runtime_document()

    skipped = select_skipped_runtimes(
        document,
        ["prompt_injection_detector"],
    )

    assert skipped == ["prompt_injection_detector"]


def test_starting_runtime_fails_closed_instead_of_being_skipped():
    document = runtime_document(embedding="starting")

    with pytest.raises(SmokeRuntimeSelectionError, match="still transitioning: embedding"):
        select_skipped_runtimes(document, ["embedding"])


def test_missing_available_runtime_state_fails_closed():
    document = {
        "runtimes": [],
        "topology": [{"service_key": "embedding", "available": True}],
    }

    with pytest.raises(
        SmokeRuntimeSelectionError,
        match="runtime state missing for available runtime: embedding",
    ):
        select_skipped_runtimes(document, ["embedding"])
