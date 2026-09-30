"""compose 기동 전 preflight 게이트가 위험한 auth/exposure 조합을 막는지 검증한다.

preflight_compose.py는 `make up`이 실제 컨테이너를 띄우기 전에 통과해야
하는 fail-closed 게이트다. 여기서 통과시키면 인증 없이 노출된 스택이 그대로 뜬다.
"""

from __future__ import annotations

import importlib.util
from types import ModuleType

import pytest

from ai_model_serving.access_profile import access_profile_env_values

from .helpers import ROOT

PREFLIGHT_PATH = ROOT / "scripts/compose/preflight_compose.py"


def load_preflight() -> ModuleType:
    """preflight 스크립트를 매 테스트마다 새 모듈로 적재한다.

    이 스크립트는 import 시점에 환경을 읽으므로, 모듈을 공유하면 앞선 테스트의
    monkeypatch 결과가 뒤 테스트로 새어 들어간다.
    """
    spec = importlib.util.spec_from_file_location("preflight_compose_under_test", PREFLIGHT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_runtime_effective_for_dynamic_reference_policy(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-nvidia-dynamic")
    monkeypatch.delenv("MAIN_MODEL_RESOURCE_VARIANT", raising=False)

    assert module._prompt_runtime_effective() is True


def test_prompt_runtime_not_effective_for_4090_resource_policy(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-nvidia-dynamic")
    monkeypatch.setenv("MAIN_MODEL_RESOURCE_VARIANT", "rtx4090-24gb")

    assert module._prompt_runtime_effective() is False


def test_prompt_runtime_not_effective_for_static_target(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("DEPLOYMENT_TARGET", "linux-nvidia-static")
    monkeypatch.delenv("MAIN_MODEL_RESOURCE_VARIANT", raising=False)

    assert module._prompt_runtime_effective() is False


def test_compose_preflight_rejects_local_open_without_local_only_policy(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "local_open")
    monkeypatch.setenv("EXPOSURE_MODE", "private_network")
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "")

    with pytest.raises(SystemExit) as exc:
        module._phase1()

    assert "auth profile evidence" in str(exc.value)


def test_compose_preflight_allows_local_open_private_local_only_policy(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "local_open")
    monkeypatch.setenv("EXPOSURE_MODE", "private_network")
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "local_only")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "127.0.0.1")
    monkeypatch.setenv("GRAFANA_BIND_ADDR", "127.0.0.1")

    module._check_auth_profile_preflight()


def test_compose_preflight_rejects_local_only_with_non_loopback_public_bind(monkeypatch) -> None:
    module = load_preflight()

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "local_open")
    monkeypatch.setenv("EXPOSURE_MODE", "private_network")
    monkeypatch.setenv("EXPOSURE_AUDIENCE", "local_only")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "0.0.0.0")
    monkeypatch.setenv("GRAFANA_BIND_ADDR", "127.0.0.1")

    with pytest.raises(SystemExit) as exc:
        module._check_auth_profile_preflight()

    assert "auth profile evidence" in str(exc.value)


def test_compose_preflight_rejects_access_profile_drift(monkeypatch) -> None:
    module = load_preflight()
    for key, value in access_profile_env_values("local").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("GATEWAY_BIND_ADDR", "0.0.0.0")

    with pytest.raises(SystemExit) as exc:
        module._check_auth_profile_preflight()

    assert "auth/exposure policy" in str(exc.value)


def test_compose_preflight_reads_auth_mode_from_env_file(monkeypatch, tmp_path) -> None:
    module = load_preflight()

    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=production\nAUTH_MODE=local_open\n", encoding="utf-8")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(env_file))

    with pytest.raises(SystemExit):
        module._phase1()


def test_compose_preflight_reads_exposure_from_env_file(monkeypatch, tmp_path) -> None:
    module = load_preflight()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=local\nAUTH_MODE=local_open\nEXPOSURE_MODE=master_open\nEXPOSURE_AUDIENCE=banana\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("EXPOSURE_MODE", raising=False)
    monkeypatch.delenv("EXPOSURE_AUDIENCE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(env_file))

    with pytest.raises(SystemExit):
        module._phase1()
