from __future__ import annotations

import json

from ai_model_serving.docs_ui import SCALAR_BUNDLE, SCALAR_CONFIG, scalar_html


def test_scalar_config_is_explicitly_on_prem() -> None:
    config = json.loads(SCALAR_CONFIG)

    assert config["agent"] == {"disabled": True}
    assert config["telemetry"] is False
    assert config["withDefaultFonts"] is False
    assert config["modelsSectionLabel"] == "Schemas"


def test_scalar_html_uses_the_vendored_same_origin_bundle() -> None:
    html = scalar_html("/openapi.json", "Gateway API")

    assert f'src="{SCALAR_BUNDLE.route}"' in html
    assert SCALAR_BUNDLE.integrity in html
    assert "fonts.scalar.com" not in html
    assert "cdn.jsdelivr.net" not in html
