from __future__ import annotations

from scripts.validation.runtime.cli import build_parser


def test_prompt_detector_override_uses_canonical_destination() -> None:
    args = build_parser().parse_args(
        ["--prompt-injection-detector-base", "http://prompt-injection-detector-runtime:9403/v1"]
    )

    assert args.prompt_injection_detector_base == "http://prompt-injection-detector-runtime:9403/v1"
