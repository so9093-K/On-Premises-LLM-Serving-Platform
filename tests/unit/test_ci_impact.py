"""실제 영향에 대한 필수 검증 누락을 막는다."""
from __future__ import annotations

import pytest

from scripts.validation.ci_impact import CHECKS, output_lines, select_checks


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (["README.md", "docs/08_testing_validation.md"], set()),
        (["ui/control-plane/tests/chatSession.test.mjs"], {"console"}),
        (["ui/control-plane/src/ChatPage.tsx"], {"console", "browser", "platform_image"}),
        (["src/ai_model_serving/static/control-plane/index.html"], {"console", "browser", "platform_image"}),
        (["scripts/validation/console_browser_smoke.py"], {"browser"}),
        (["ops/loki/loki-config.yml"], {"loki"}),
        (["scripts/validation/grafana_loki_smoke.py"], {"loki"}),
        (["tests/unit/gateway/test_auth_and_docs.py"], {"app_tests", "macos"}),
        (["src/ai_model_serving/api/routers/gateway_runtime_control.py"], {"app_tests", "macos", "platform_image"}),
        (["docs/README.md", "ui/control-plane/src/ChatPage.tsx", "ops/loki/loki-config.yml"], {"console", "browser", "platform_image", "loki"}),
        ([".github/workflows/validate.yml"], set(CHECKS)),
        (["scripts/validation/ci_impact.py"], set(CHECKS)),
        (["pyproject.toml"], set(CHECKS)),
        (["ui/control-plane/package-lock.json"], set(CHECKS)),
        (["configs/main_model_profiles.yaml"], set(CHECKS)),
        (["unknown/new/path"], set(CHECKS)),
        ([], set(CHECKS)),
    ],
)
def test_selection_requires_checks_for_product_risk(paths, expected):
    checks = select_checks(paths)
    assert {key for key, value in checks.items() if value} == expected
    assert set(checks) == set(CHECKS)


def test_manual_dispatch_never_selects_partial_validation():
    assert all(select_checks(["README.md"], full=True).values())


def test_matrix_preserves_ubuntu_and_app_macos_invariant():
    docs = output_lines(select_checks(["README.md"]))
    app = output_lines(select_checks(["tests/unit/gateway/test_auth_and_docs.py"]))
    assert 'matrix={"include":[{"os":"ubuntu-24.04","python_version":"3.12"}]}' in docs
    assert '{"os":"macos-15","python_version":"3.13"}' in app[-1]
    assert "app_tests=false" in docs
    assert "app_tests=true" in app
