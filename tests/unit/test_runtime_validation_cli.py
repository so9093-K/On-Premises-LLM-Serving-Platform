from __future__ import annotations

import pytest

from scripts.validation.runtime.cli import build_parser


def test_runtime_validation_parser_rejects_retired_network_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--network-scope", "compose"])


def test_prompt_detector_override_uses_canonical_destination_with_legacy_alias() -> None:
    parser = build_parser()

    canonical = parser.parse_args(
        ["--prompt-injection-detector-base", "http://prompt-injection-detector-runtime:9403/v1"]
    )
    legacy = parser.parse_args(["--risk-prompt-base", "http://legacy-prompt:9403/v1"])

    assert canonical.prompt_injection_detector_base == "http://prompt-injection-detector-runtime:9403/v1"
    assert legacy.prompt_injection_detector_base == "http://legacy-prompt:9403/v1"
