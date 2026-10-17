"""Main Model Catalog의 image identity, capability, resource-variant 계약을 검증한다.

Config projection과 profile 선택 정책을 관리하며 Manager의 실행 상태 머신은
test_main_model_control.py에서 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_model_serving.main_model.catalog import (
    MainModelConfigurationError,
    load_main_model_catalog,
    resolve_boot_profile,
    resource_variant_from_mapping,
)
from ai_model_serving.main_model.control import MainModelManager, MainModelSwitchError
from ai_model_serving.main_model.state import MainModelStateStore
from tests.support.main_model import (
    FakeBackend, _LOCAL_IMAGE, _PROFILE_IMAGE, _REV_A, _REV_B, _SHARED_IMAGE,
)

ROOT = Path(__file__).resolve().parents[2]


def _catalog_yaml(*, profile_image: str | None) -> str:
    audio_line = f"\n    image: {profile_image}" if profile_image is not None else ""
    return f"""
version: 1
public_model: local-main
default_profile: base
runtime:
  compose_service: main-llm-vllm
  image: {_SHARED_IMAGE}
profiles:
  base:
    display_name: Base
    model_id: org/base
    revision: "{_REV_A}"
    served_model_name: local-main
    compatibility:
      status: compatible
    qualification:
      status: verified
    command: [--host, 0.0.0.0]
  audio:
    display_name: Audio{audio_line}
    model_id: org/audio
    revision: "{_REV_B}"
    served_model_name: local-main
    compatibility:
      status: compatible
    qualification:
      status: verified
    command: [--host, 0.0.0.0]
"""


def _write_catalog_path(tmp_path, *, profile_image: str | None = None):
    path = tmp_path / "profiles.yaml"
    path.write_text(_catalog_yaml(profile_image=profile_image), encoding="utf-8")
    return path


def _write_catalog(tmp_path, *, profile_image: str | None, env: dict[str, str] | None = None):
    return load_main_model_catalog(
        _write_catalog_path(tmp_path, profile_image=profile_image), env=env
    )


def test_profile_image_env_ref_resolves_from_env(tmp_path):
    # CI/배포가 불변 digest를 주입한다; 프로필은 ${MAIN_MODEL_VLLM_IMAGE_OVERRIDE}를 고정 참조한다.
    loaded = _write_catalog(
        tmp_path, profile_image="${MAIN_MODEL_VLLM_IMAGE_OVERRIDE}", env={"MAIN_MODEL_VLLM_IMAGE_OVERRIDE": _PROFILE_IMAGE}
    )
    assert loaded.profiles["audio"].image == _PROFILE_IMAGE
    assert loaded.profiles["base"].image == _SHARED_IMAGE


def test_runtime_image_env_ref_resolves_before_profiles_inherit_it(tmp_path):
    path = _write_catalog_path(tmp_path, profile_image=None)
    raw = path.read_text(encoding="utf-8").replace(
        f"image: {_SHARED_IMAGE}", "image: ${VLLM_IMAGE}", 1
    )
    path.write_text(raw, encoding="utf-8")
    loaded = load_main_model_catalog(path, env={"VLLM_IMAGE": _PROFILE_IMAGE})
    assert loaded.runtime["image"] == _PROFILE_IMAGE
    assert loaded.profiles["base"].image == _PROFILE_IMAGE


def test_runtime_image_accepts_immutable_local_docker_image_id(tmp_path):
    path = _write_catalog_path(tmp_path, profile_image=None)
    raw = path.read_text(encoding="utf-8").replace(
        f"image: {_SHARED_IMAGE}", "image: ${VLLM_IMAGE}", 1
    )
    path.write_text(raw, encoding="utf-8")
    loaded = load_main_model_catalog(path, env={"VLLM_IMAGE": _LOCAL_IMAGE})
    assert loaded.profiles["base"].image == _LOCAL_IMAGE


def test_profile_image_env_ref_falls_back_to_shared_when_unset(tmp_path):
    # 아직 digest가 빌드되지 않음 -> env가 비어있음 -> 프로필이 공유 base를
    # 상속한다, 그래도 sidecar는 부팅된다(go-live를 막는 건 pin이 아니라
    # media boot canary다).
    loaded = _write_catalog(tmp_path, profile_image="${MAIN_MODEL_VLLM_IMAGE_OVERRIDE}", env={})
    assert loaded.profiles["audio"].image == _SHARED_IMAGE


def test_profile_image_env_ref_rejects_non_digest_value(tmp_path):
    with pytest.raises(MainModelConfigurationError):
        _write_catalog(
            tmp_path,
            profile_image="${MAIN_MODEL_VLLM_IMAGE_OVERRIDE}",
            env={"MAIN_MODEL_VLLM_IMAGE_OVERRIDE": "registry.example.com/vllm-profile:latest"},
        )


def test_profile_without_image_inherits_shared_runtime_image(tmp_path):
    loaded = _write_catalog(tmp_path, profile_image=None)
    # 어느 프로필도 이미지를 고정하지 않음 -> 둘 다 공유 runtime.image로
    # 귀결된다, 그래서 프로필 전환이 26b를 받치는 runtime을 조용히 바꾸는 일은 없다.
    assert loaded.profiles["base"].image == _SHARED_IMAGE
    assert loaded.profiles["audio"].image == _SHARED_IMAGE
    assert loaded.profiles["base"].public_view()["runtime_image"] == _SHARED_IMAGE


def test_profile_image_override_travels_with_profile(tmp_path):
    loaded = _write_catalog(tmp_path, profile_image=_PROFILE_IMAGE)
    # audio 프로필은 자신만의 runtime을 고정한다; base 프로필은 영향받지 않는다.
    assert loaded.profiles["base"].image == _SHARED_IMAGE
    assert loaded.profiles["audio"].image == _PROFILE_IMAGE


def test_profile_image_must_be_digest_pinned(tmp_path):
    with pytest.raises(MainModelConfigurationError):
        _write_catalog(tmp_path, profile_image="registry.example.com/vllm-profile:latest")


def test_snapshot_runtime_image_reflects_active_profile(tmp_path):
    loaded = _write_catalog(tmp_path, profile_image=_PROFILE_IMAGE)
    store = MainModelStateStore(tmp_path / "state.json", loaded.default_profile)
    store.write({**store.read(), "active_profile": "audio", "gate": "open"})
    manager = MainModelManager(loaded, store, FakeBackend("audio"))
    # 실제 runtime 이미지는 공유 기본값이 아니라 active profile을 따라간다.
    assert manager.snapshot()["runtime_image"] == _PROFILE_IMAGE


def test_deployed_input_rejects_unknown_modality(tmp_path):
    # "imgae" 같은 오타가 loader를 통과하면 Gateway 모델 정보엔 노출되면서도
    # switch-time canary는 정확한 문자열("image")만 알아서 절대 검증되지 않는 modality가
    # "지원"으로 선언될 수 있다 -- 이 조합을 loader에서 막는다.
    path = _write_catalog_path(tmp_path, profile_image=None)
    raw = path.read_text(encoding="utf-8").replace(
        "    compatibility:\n      status: compatible\n    qualification:\n      status: verified\n    command: [--host, 0.0.0.0]",
        "    compatibility:\n      status: compatible\n    qualification:\n      status: verified\n    capabilities:\n      deployed_input: [text, imgae]\n"
        "    command: [--host, 0.0.0.0]",
        1,
    )
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(MainModelConfigurationError):
        load_main_model_catalog(path)


def test_capabilities_rejects_unknown_fields(tmp_path):
    path = _write_catalog_path(tmp_path, profile_image=None)
    raw = path.read_text(encoding="utf-8").replace(
        "    compatibility:\n      status: compatible\n    qualification:\n      status: verified\n    command: [--host, 0.0.0.0]",
        "    compatibility:\n      status: compatible\n    qualification:\n      status: verified\n    capabilities:\n      deployed_input: [text]\n"
        "      unsupported_flag: false\n    command: [--host, 0.0.0.0]",
        1,
    )
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(MainModelConfigurationError, match="unsupported key"):
        load_main_model_catalog(path)


def test_gpu_util_override_rewrites_command_and_fraction():
    from ai_model_serving.main_model.catalog import load_main_model_catalog as _load

    loaded = _load(ROOT / "configs/main_model_profiles.yaml", gpu_memory_utilization_override=0.55)
    # override는 모든 프로필에 대해 runtime command와 파싱된 budget cost 양쪽에
    # 동시에(lockstep) 반영된다 (호스트별 용량 조절 손잡이).
    for profile in loaded.profiles.values():
        cmd = list(profile.command)
        assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.55"
        assert profile.vram_fraction == 0.55
        assert profile.resolved_engine_policy.public_view() == profile.engine_policy()


def test_gpu_util_override_appends_when_command_omits_flag(tmp_path):
    # base/audio 픽스처에는 --gpu-memory-utilization이 없다; override가 이를 추가한다.
    loaded = load_main_model_catalog(
        _write_catalog_path(tmp_path), gpu_memory_utilization_override=0.5
    )
    cmd = list(loaded.profiles["base"].command)
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.5"
    assert loaded.profiles["base"].vram_fraction == 0.5


def test_gpu_util_override_from_mapping_parses_and_validates():
    from ai_model_serving.main_model.catalog import gpu_util_override_from_mapping as f

    assert f({}) is None
    assert f({"MAIN_MODEL_GPU_MEMORY_UTILIZATION": ""}) is None
    assert f({"MAIN_MODEL_GPU_MEMORY_UTILIZATION": "0.9"}) == 0.9
    # "-0.1"은 별도로 두지 않는다: "0"이 이미 배타적 하한(0.0 < value)의 경계를
    # 검증하므로, 그보다 더 작은 음수는 동일한 range-check 분기를 반복 확인할 뿐이다.
    for bad in ("abc", "0", "1.5"):
        with pytest.raises(MainModelConfigurationError):
            f({"MAIN_MODEL_GPU_MEMORY_UTILIZATION": bad})


def _flag(command, flag):
    command = list(command)
    return command[command.index(flag) + 1]


def _variant_catalog(variant, **kwargs):
    return load_main_model_catalog(
        ROOT / "configs/main_model_profiles.yaml",
        resource_variant=variant,
        env={"VLLM_IMAGE": _SHARED_IMAGE, "MAIN_MODEL_VLLM_IMAGE_OVERRIDE": _PROFILE_IMAGE},
        **kwargs,
    )


def test_resource_variant_overrides_only_the_declared_resource_knob() -> None:
    # 2026-09-19 RTX 4090 실측: 24GB에서 달라지는 값은 prefill workspace를 정하는
    # max_num_batched_tokens 하나뿐이고, context/seqs/util은 48GB 값 그대로 기동한다.
    # variant가 그 이상을 조용히 바꾸기 시작하면 profile이 사실상 다른 profile이 된다.
    base = _variant_catalog(None).profiles["gemma4-e4b-it"]
    tuned = _variant_catalog("rtx4090-24gb").profiles["gemma4-e4b-it"]

    assert _flag(base.command, "--max-num-batched-tokens") == "50000"
    assert _flag(tuned.command, "--max-num-batched-tokens") == "4096"
    for flag in ("--max-model-len", "--max-num-seqs", "--gpu-memory-utilization"):
        assert _flag(tuned.command, flag) == _flag(base.command, flag)
    assert tuned.model_id == base.model_id
    assert tuned.revision == base.revision
    assert tuned.capabilities == base.capabilities
    assert tuned.gateway_policy == base.gateway_policy
    assert base.engine_policy() == {
        "max_model_len": 65000,
        "max_num_seqs": 4,
        "max_num_batched_tokens": 50000,
        "gpu_memory_utilization": 0.76,
    }
    assert tuned.engine_policy() == {
        "max_model_len": 65000,
        "max_num_seqs": 4,
        "max_num_batched_tokens": 4096,
        "gpu_memory_utilization": 0.76,
    }


def test_resource_variant_is_recorded_on_the_profile_snapshot() -> None:
    # admin 응답과 request log가 이 값을 읽는다. 어떤 자원 정책으로 서빙 중인지
    # 남지 않으면 48GB 정책과 24GB 정책의 동작이 구분되지 않는다.
    tuned = _variant_catalog("rtx4090-24gb").profiles["gemma4-e4b-it"]
    assert tuned.resource_variant == "rtx4090-24gb"
    assert tuned.public_view()["resource_variant"] == "rtx4090-24gb"

    base = _variant_catalog(None).profiles["gemma4-e4b-it"]
    assert base.resource_variant is None
    assert base.public_view()["resource_variant"] is None
    # 선언 목록은 선택 여부와 무관하게 노출된다.
    assert "rtx4090-24gb" in base.public_view()["resource_variants"]


def test_profiles_without_the_selected_resource_override_are_not_selectable() -> None:
    # 명시적으로 24GB용 resource-policy override를 선택한 host에서는 그 override가
    # 없는 profile이 reference 정책으로 조용히 fallback하면 안 된다. 이 검사는 GPU
    # 제품 allowlist가 아니라 operator가 선택한 자원 정책의 fail-closed 경계다.
    loaded = _variant_catalog("rtx4090-24gb")
    assert loaded.resource_variant == "rtx4090-24gb"
    assert loaded.missing_selected_resource_policy("gemma4-e4b-it") is None
    for profile_id in ("gemma4-12b-unified-fp8", "gemma4-26b-a4b-fp8"):
        assert loaded.missing_selected_resource_policy(profile_id) == "rtx4090-24gb"


def test_reference_host_leaves_every_profile_selectable() -> None:
    loaded = _variant_catalog(None)
    assert loaded.resource_variant is None
    for profile_id in loaded.profiles:
        assert loaded.missing_selected_resource_policy(profile_id) is None


def test_switch_without_the_selected_resource_override_is_refused(tmp_path) -> None:
    loaded = _variant_catalog("rtx4090-24gb")
    loaded.runtime["drain_timeout_seconds"] = 0
    store = MainModelStateStore(tmp_path / "state.json", "gemma4-e4b-it")
    manager = MainModelManager(loaded, store, FakeBackend(), boot_profile="gemma4-e4b-it")
    with pytest.raises(MainModelSwitchError) as error:
        manager.request_switch("gemma4-26b-a4b-fp8")
    assert error.value.code == "MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED"


def test_resource_override_refusal_is_not_bypassed_by_unverified_confirmation(tmp_path) -> None:
    # confirm_unverified는 검증 여부 축의 확인이지 자원 정책의 확인이 아니다.
    # boot reconcile이 이 flag를 켜고 같은 경로를 지나므로, 여기서 우회가 되면
    # 재기동만으로 reference 자원 정책이 이 host에 다시 적용된다.
    loaded = _variant_catalog("rtx4090-24gb")
    loaded.runtime["drain_timeout_seconds"] = 0
    store = MainModelStateStore(tmp_path / "state.json", "gemma4-e4b-it")
    manager = MainModelManager(loaded, store, FakeBackend(), boot_profile="gemma4-e4b-it")
    with pytest.raises(MainModelSwitchError) as error:
        manager.request_switch(
            "gemma4-12b-unified-fp8", confirm_unverified=True, boot_reconcile=True
        )
    assert error.value.code == "MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED"


def test_boot_refuses_a_profile_without_the_selected_resource_override() -> None:
    loaded = _variant_catalog("rtx4090-24gb")
    # default_profile(12B)은 이 host의 자원 정책을 선언하지 않으므로 boot에서 걸린다.
    with pytest.raises(MainModelConfigurationError):
        resolve_boot_profile(
            loaded, configured_profile=None, locked=False, persisted_profile=None
        )
    # persisted 상태로 되살아나는 경로도 같은 검사를 지난다.
    with pytest.raises(MainModelConfigurationError):
        resolve_boot_profile(
            loaded,
            configured_profile="gemma4-e4b-it",
            locked=False,
            persisted_profile="gemma4-26b-a4b-fp8",
        )
    assert (
        resolve_boot_profile(
            loaded, configured_profile="gemma4-e4b-it", locked=True, persisted_profile=None
        )
        == "gemma4-e4b-it"
    )


def test_unknown_resource_variant_fails_instead_of_booting_reference_values() -> None:
    # 조용한 fallback은 48GB 자원 정책이 24GB GPU에서 그대로 기동을 시도하게 만드는
    # 경로다. 오타는 반드시 기동 실패로 드러나야 한다.
    with pytest.raises(MainModelConfigurationError) as excinfo:
        _variant_catalog("rtx4090-24g")
    assert "rtx4090-24g" in str(excinfo.value)


def test_gpu_util_env_override_still_wins_over_a_variant() -> None:
    # variant는 catalog가 소유한 검토된 resource policy이고,
    # MAIN_MODEL_GPU_MEMORY_UTILIZATION은 단일 호스트용 escape hatch다.
    # 후자가 항상 마지막 발언권을 갖고, vram_fraction도 그 값을 따라간다.
    tuned = _variant_catalog("rtx4090-24gb", gpu_memory_utilization_override=0.8)
    profile = tuned.profiles["gemma4-e4b-it"]
    assert _flag(profile.command, "--gpu-memory-utilization") == "0.8"
    assert profile.vram_fraction == 0.8
    assert _flag(profile.command, "--max-num-batched-tokens") == "4096"


def test_resource_variant_env_parsing_rejects_malformed_ids() -> None:
    assert resource_variant_from_mapping({}) is None
    assert resource_variant_from_mapping({"MAIN_MODEL_RESOURCE_VARIANT": "  "}) is None
    assert (
        resource_variant_from_mapping({"MAIN_MODEL_RESOURCE_VARIANT": " rtx4090-24gb "})
        == "rtx4090-24gb"
    )
    with pytest.raises(MainModelConfigurationError):
        resource_variant_from_mapping({"MAIN_MODEL_RESOURCE_VARIANT": "RTX4090"})


def test_resource_variant_rejects_fractional_integer_knob(tmp_path):
    import yaml

    raw = yaml.safe_load((ROOT / "configs/main_model_profiles.yaml").read_text())
    profile = raw["profiles"]["gemma4-e4b-it"]
    profile["resource_variants"]["fractional-invalid"] = {"max_num_seqs": 1.5}
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(MainModelConfigurationError, match="must be an integer"):
        load_main_model_catalog(
            path,
            env={"VLLM_IMAGE": _SHARED_IMAGE, "MAIN_MODEL_VLLM_IMAGE_OVERRIDE": _PROFILE_IMAGE},
        )


def test_resource_variant_may_not_change_model_identity_or_policy(tmp_path) -> None:
    import yaml

    raw = yaml.safe_load((ROOT / "configs/main_model_profiles.yaml").read_text(encoding="utf-8"))
    raw["profiles"]["gemma4-e4b-it"]["resource_variants"]["rtx4090-24gb"]["revision"] = "b" * 40
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(MainModelConfigurationError) as excinfo:
        load_main_model_catalog(
            path,
            resource_variant="rtx4090-24gb",
            env={"VLLM_IMAGE": _SHARED_IMAGE, "MAIN_MODEL_VLLM_IMAGE_OVERRIDE": _PROFILE_IMAGE},
        )
    assert "unsupported key" in str(excinfo.value)


def test_variant_max_model_len_is_projected_into_gateway_limits(tmp_path) -> None:
    # engine 한도와 Gateway admission이 갈라지면, Gateway가 engine이 곧바로 거부할
    # 요청을 통과시키거나 서빙 가능한 요청을 막는다. variant가 context를 옮기면
    # Gateway 선제 검사도 같은 값을 따라가야 한다.
    import yaml

    raw = yaml.safe_load((ROOT / "configs/main_model_profiles.yaml").read_text(encoding="utf-8"))
    raw["profiles"]["gemma4-e4b-it"]["resource_variants"]["rtx4090-24gb"]["max_model_len"] = 32000
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    loaded = load_main_model_catalog(
        path,
        resource_variant="rtx4090-24gb",
        env={"VLLM_IMAGE": _SHARED_IMAGE, "MAIN_MODEL_VLLM_IMAGE_OVERRIDE": _PROFILE_IMAGE},
    )
    profile = loaded.profiles["gemma4-e4b-it"]
    assert _flag(profile.command, "--max-model-len") == "32000"
    assert profile.gateway_policy["request_limits"]["max_model_len"] == 32000
