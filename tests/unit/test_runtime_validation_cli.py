from __future__ import annotations

from types import SimpleNamespace

from scripts.validation.runtime.config import _url_value


def test_runtime_validation_endpoint_precedence(monkeypatch) -> None:
    args = SimpleNamespace(gateway_base=" http://cli.example/v1/ ")
    monkeypatch.setenv(
        "RUNTIME_VALIDATION_GATEWAY_BASE_URL",
        "http://env.example/v1/",
    )

    assert (
        _url_value(
            args,
            "gateway_base",
            "RUNTIME_VALIDATION_GATEWAY_BASE_URL",
            "http://derived.internal/v1/",
        )
        == "http://cli.example/v1"
    )

    args.gateway_base = "   "
    assert (
        _url_value(
            args,
            "gateway_base",
            "RUNTIME_VALIDATION_GATEWAY_BASE_URL",
            "http://derived.internal/v1/",
        )
        == "http://env.example/v1"
    )

    monkeypatch.delenv("RUNTIME_VALIDATION_GATEWAY_BASE_URL")
    assert (
        _url_value(
            args,
            "gateway_base",
            "RUNTIME_VALIDATION_GATEWAY_BASE_URL",
            "http://derived.internal/v1/",
        )
        == "http://derived.internal/v1"
    )
