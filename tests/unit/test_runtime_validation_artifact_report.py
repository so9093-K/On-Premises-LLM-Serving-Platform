from __future__ import annotations

import json

from scripts.validation.runtime.reporting import write_reports
from scripts.validation.runtime.results import CheckResult


def test_runtime_report_preserves_observed_artifact(tmp_path) -> None:
    artifact = {
        "profile_id": "gemma4-12b-unified-fp8",
        "image_ref": "registry.example/vllm@sha256:" + "a" * 64,
        "image_id": "sha256:" + "b" * 64,
        "image_digest": "sha256:" + "a" * 64,
        "runtime_engine": {"name": "vllm", "version": "0.30.0"},
    }
    json_path, md_path = write_reports(
        root=tmp_path,
        output_dir="reports/runtime",
        version="0.0.1",
        session_started="2026-10-02T00:00:00+00:00",
        mode="live",
        results=[CheckResult("vllm-runtime", "main runtime artifact", "pass", details=artifact)],
    )

    assert json.loads(json_path.read_text(encoding="utf-8"))["runtime_artifact"] == artifact
    assert artifact["image_digest"] in md_path.read_text(encoding="utf-8")
