from __future__ import annotations

from scripts.validation.governance.terminology import terminology_violations


def test_user_facing_noncanonical_term_is_reported(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "01_overview.md").write_text("Admin Sidecar controls runtimes.\n", encoding="utf-8")

    violations = terminology_violations(tmp_path)

    assert violations == [
        "docs/01_overview.md:1: noncanonical display term 'Admin Sidecar'; use 'Runtime Controller'"
    ]


def test_compound_noncanonical_runtime_controller_term_is_reported(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "03_system_components.md").write_text(
        "Admin / Control Sidecar controls runtimes.\n",
        encoding="utf-8",
    )

    assert terminology_violations(tmp_path) == [
        "docs/03_system_components.md:1: noncanonical display term "
        "'Admin / Control Sidecar'; use 'Runtime Controller'"
    ]


def test_lowercase_noncanonical_runtime_controller_term_is_reported(tmp_path):
    src = tmp_path / "src" / "ai_model_serving"
    src.mkdir(parents=True)
    (src / "api_examples.py").write_text(
        'DETAIL = "admin sidecar is not configured"\n',
        encoding="utf-8",
    )

    assert terminology_violations(tmp_path) == [
        "src/ai_model_serving/api_examples.py:1: noncanonical display term "
        "'admin sidecar'; use 'Runtime Controller'"
    ]


def test_runtime_cli_noncanonical_service_term_is_reported(tmp_path):
    cli = tmp_path / "scripts" / "validation" / "runtime"
    cli.mkdir(parents=True)
    (cli / "cli.py").write_text(
        'HELP = "Risk Adapter base URL"\n',
        encoding="utf-8",
    )

    assert terminology_violations(tmp_path) == [
        "scripts/validation/runtime/cli.py:1: noncanonical display term "
        "'Risk Adapter'; use 'Risk Signal Service'"
    ]


def test_adr_history_is_outside_display_terminology_gate(tmp_path):
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-history.md").write_text("Risk Adapter was the old name.\n", encoding="utf-8")

    assert terminology_violations(tmp_path) == []


def test_retired_deployment_semantics_are_reported_in_current_contract(tmp_path):
    docs = tmp_path / "docs"
    configs = tmp_path / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "13_change_guide.md").write_text(
        "배포 스크립트 변경은 Rolling / Full 결정에 영향을 준다.\n",
        encoding="utf-8",
    )
    (configs / "deploy_profiles.yaml").write_text(
        "# compose-up과 full 배포가 공통으로 사용하는 Runtime Startup Profile\n",
        encoding="utf-8",
    )

    assert terminology_violations(tmp_path) == [
        "docs/13_change_guide.md:1: retired deployment term "
        "'Rolling / Full'; use 'canonical local lifecycle'",
        "configs/deploy_profiles.yaml:1: retired deployment term "
        "'compose-up과 full 배포'; use 'full-stack compose-up'",
    ]


def test_retired_deployment_history_is_outside_current_contract_gate(tmp_path):
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0037-history.md").write_text(
        "The removed path selected Rolling / Full and Release 활성화.\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "Removed remote rolling/full release state machine.\n",
        encoding="utf-8",
    )

    assert terminology_violations(tmp_path) == []
