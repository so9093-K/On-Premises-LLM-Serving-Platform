from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..image_refs import is_immutable_image_ref
from .engine_policy import VllmEnginePolicy
from .profile_state import validate_profile_state

_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
# 프로필 이미지는 리터럴 digest이거나 CI/deploy가 이를 resolve하는 단일 ${ENV_VAR} 참조일 수 있다 —
# Compose의 `${VLLM_IMAGE}`와 동일한 방식으로, profile-specific runtime image가
# 수동이 아니라 파이프라인에 의해 고정(pin)된다.
_IMAGE_ENV_REF_RE = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
# switch-time media boot canary가 실제로 아는 modality 집합이다. deployed_input은 이
# 값들로만 구성돼야 한다 -- 그래야 "선언한 modality는 반드시 canary된다"는 원칙이 오타나
# 미지원 값(예: "imgae") 앞에서도 깨지지 않는다.
_ALLOWED_MODALITIES = frozenset({"text", "image", "audio", "video"})
# 프로필 command가 직접 적어서는 안 되는 신원 flag. 선언 필드가 소유한다.
_IDENTITY_FLAGS = ("--model", "--revision", "--served-model-name")
# capabilities의 현재 schema는 deployed_input 하나만 허용한다. 새 field는 별도
# contract 변경 없이 조용히 무시하지 않고 fail-closed한다.
_ALLOWED_CAPABILITY_KEYS = frozenset({"deployed_input"})
class MainModelConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class MainModelProfile:
    profile_id: str
    display_name: str
    model_id: str
    revision: str
    served_model_name: str
    command: tuple[str, ...]
    compatibility: dict[str, Any]
    qualification: dict[str, Any]
    capabilities: dict[str, Any]
    # Gateway가 이 프로필을 실제로 서빙할 때 적용할 입력 한도·요청 파라미터·
    # vLLM 기능 계약이다. active_profile snapshot에 함께 실어 Gateway가 전환된
    # runtime과 다른 정적 정책을 쓰지 않게 한다.
    gateway_policy: dict[str, Any]
    # 이 프로필에 대해 resolve된 런타임 이미지: 프로필이 자체 이미지를 고정하는 경우
    # (예: audio 지원 런타임) 프로필 레벨 오버라이드이고, 그렇지 않으면 공유된
    # runtime.image이다. 필수 값이며(loader가 유일한 생성자이고 항상 digest로 고정된
    # 값으로 resolve하므로) 빈 이미지가 Docker 경계까지 도달하는 일은 절대 없다.
    # 따라서 런타임 capability(예: audio 디코드 라이브러리)는 활성 프로필과 함께 이동한다.
    image: str
    # resource variant와 host override까지 적용된 final command에서 loader가 한 번
    # resolve한 capacity 관련 vLLM policy다. Serving Envelope와 GPU budget은 이 값을
    # 소비하고 command 문자열을 각자 다시 해석하지 않는다.
    resolved_engine_policy: VllmEnginePolicy
    # 이 host에 실제로 적용된 resource variant. base 자원 정책으로 서빙 중이면
    # None이다. admin 응답과 request log가 이 값을 함께 보여주므로, 같은 profile이
    # 어떤 자원 정책으로 서빙 중인지 구분된다.
    resource_variant: str | None = None
    # 이 profile이 선언한 모든 variant id다(선택 여부와 무관).
    resource_variants: tuple[str, ...] = ()

    @property
    def vram_fraction(self) -> float:
        return self.resolved_engine_policy.gpu_memory_utilization

    def engine_policy(self) -> dict[str, Any]:
        """Resolved vLLM resource knobs safe to expose as serving context."""
        return self.resolved_engine_policy.public_view()

    def public_view(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "display_name": self.display_name,
            "served_model_name": self.served_model_name,
            "upstream_model_id": self.model_id,
            "revision": self.revision,
            "compatibility": self.compatibility,
            "qualification": self.qualification,
            "capabilities": self.capabilities,
            "gateway_policy": self.gateway_policy,
            "runtime_image": self.image,
            "vram_fraction": self.vram_fraction,
            "resource_variant": self.resource_variant,
            "resource_variants": list(self.resource_variants),
        }


@dataclass(frozen=True)
class MainModelCatalog:
    public_model: str
    default_profile: str
    runtime: dict[str, Any]
    profiles: dict[str, MainModelProfile]
    # 운영자가 이 host에 명시적으로 선택한 resource-policy override다.
    # None이면 GPU 제품명이 알려졌다는 뜻이 아니라 profile의 reference 자원 정책을
    # 그대로 사용한다는 뜻이다. variant는 hardware allowlist가 아니다.
    resource_variant: str | None = None

    def missing_selected_resource_policy(self, profile_id: str) -> str | None:
        """선택된 resource-policy override를 profile이 선언하지 않으면 그 id를 반환한다.

        이 검사는 GPU 제품 지원 여부를 판단하지 않는다. 운영자가 명시적으로
        MAIN_MODEL_RESOURCE_VARIANT를 선택했다는 것은 reference 정책이 이 host에
        적합하지 않다는 의도를 표현한 것이므로, 해당 override가 없는 profile에서
        reference 정책으로 조용히 fallback하는 것만 막는다.
        """
        if self.resource_variant is None:
            return None
        profile = self.profiles.get(profile_id)
        if profile is None or profile.resource_variant == self.resource_variant:
            return None
        return self.resource_variant


# main model의 --gpu-memory-utilization에 대한 호스트별 오버라이드. catalog 값은
# 기준 호스트(reference-host)의 기본값이며, GPU가 다른 호스트는 공유 catalog를 수정하지
# 않고도 동일한 프로필이 맞도록 이 값을 설정한다. 이는 *해당 호스트*의 VRAM 대비 비율이므로,
# GPU가 작을수록 더 큰 비율을 설정하게 된다.
GPU_UTIL_OVERRIDE_ENV = "MAIN_MODEL_GPU_MEMORY_UTILIZATION"

def gpu_util_override_from_mapping(mapping: dict[str, str]) -> float | None:
    """호스트별 gpu-memory-utilization override를 파싱하고 없으면 ``None``을 반환한다."""
    raw = mapping.get(GPU_UTIL_OVERRIDE_ENV, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise MainModelConfigurationError(
            f"{GPU_UTIL_OVERRIDE_ENV} must be a number in (0, 1]"
        ) from exc
    if not 0.0 < value <= 1.0:
        raise MainModelConfigurationError(f"{GPU_UTIL_OVERRIDE_ENV} must be in (0, 1]")
    return value


# 필요한 host에서만 쓰는 명시적 runtime resource-policy override다. catalog의
# command는 reference policy이고, 그 정책이 맞지 않는 host는 profile을 복제하지
# 않고 여기서 자원 knob만 덮어쓴다. 새 GPU 제품명이 보였다는 이유만으로 variant를
# 만들 필요는 없다. model/revision/capabilities/gateway 정책은 변하지 않으므로
# profile은 계속 하나의 identity다 -- 달라지는 것은 자원 정책뿐이다.
#
# 이 경계가 필요한 이유는 GPU budget이 VRAM 총량 대비 *비율*로 표현되는 반면,
# 그 비율이 덮어야 하는 것(weight, CUDA context, prefill activation workspace,
# reserve)은 *절대량*이기 때문이다. 48GB에서 정한 비율은 24GB로 이전되지 않는다.
RESOURCE_VARIANT_ENV = "MAIN_MODEL_RESOURCE_VARIANT"
# variant가 덮을 수 있는 knob과 대응하는 vLLM flag다. 자원 정책만 허용하고
# 모델 신원·capability·gateway 계약은 variant로 바꿀 수 없다.
_RESOURCE_VARIANT_FLAGS: dict[str, tuple[str, type]] = {
    "max_model_len": ("--max-model-len", int),
    "max_num_seqs": ("--max-num-seqs", int),
    "max_num_batched_tokens": ("--max-num-batched-tokens", int),
    "gpu_memory_utilization": ("--gpu-memory-utilization", float),
}
_RESOURCE_VARIANT_METADATA_KEYS = frozenset({"display_name", "description"})
_RESOURCE_VARIANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def resource_variant_from_mapping(mapping: dict[str, str]) -> str | None:
    """호스트별 resource variant 선택을 파싱하고 없으면 ``None``을 반환한다."""
    raw = mapping.get(RESOURCE_VARIANT_ENV, "").strip()
    if not raw:
        return None
    if not _RESOURCE_VARIANT_ID_RE.fullmatch(raw):
        raise MainModelConfigurationError(
            f"{RESOURCE_VARIANT_ENV} must be a lowercase id like 'rtx4090-24gb'"
        )
    return raw


def _parse_resource_variants(profile_id: str, raw: object) -> dict[str, dict[str, Any]]:
    """profile의 ``resource_variants`` 블록을 검증한다.

    선택되지 않은 variant도 전부 검증한다. 오타가 있는 variant는 그 host에
    배포되는 순간이 아니라 catalog를 읽는 모든 곳에서 즉시 실패해야 한다.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise MainModelConfigurationError(
            f"profile {profile_id} resource_variants must be a non-empty object"
        )
    parsed: dict[str, dict[str, Any]] = {}
    for variant_id, spec in raw.items():
        name = str(variant_id)
        if not _RESOURCE_VARIANT_ID_RE.fullmatch(name):
            raise MainModelConfigurationError(
                f"profile {profile_id} resource variant id {name!r} must be lowercase "
                "alphanumeric with hyphens"
            )
        if not isinstance(spec, dict):
            raise MainModelConfigurationError(
                f"profile {profile_id} resource variant {name} must be an object"
            )
        unknown = set(spec) - set(_RESOURCE_VARIANT_FLAGS) - _RESOURCE_VARIANT_METADATA_KEYS
        if unknown:
            raise MainModelConfigurationError(
                f"profile {profile_id} resource variant {name} has unsupported key(s): "
                f"{sorted(unknown)}; a variant may only override "
                f"{sorted(_RESOURCE_VARIANT_FLAGS)}"
            )
        overrides = {key: spec[key] for key in spec if key in _RESOURCE_VARIANT_FLAGS}
        if not overrides:
            raise MainModelConfigurationError(
                f"profile {profile_id} resource variant {name} must override at least one of "
                f"{sorted(_RESOURCE_VARIANT_FLAGS)}"
            )
        normalized: dict[str, Any] = {}
        for key, value in overrides.items():
            _, caster = _RESOURCE_VARIANT_FLAGS[key]
            if isinstance(value, bool):
                raise MainModelConfigurationError(
                    f"profile {profile_id} resource variant {name}.{key} must be a number"
                )
            try:
                cast = caster(value)
            except (TypeError, ValueError) as exc:
                raise MainModelConfigurationError(
                    f"profile {profile_id} resource variant {name}.{key} must be a "
                    f"{caster.__name__}"
                ) from exc
            if caster is int and cast <= 0:
                raise MainModelConfigurationError(
                    f"profile {profile_id} resource variant {name}.{key} must be a positive integer"
                )
            if caster is float and not 0.0 < cast <= 1.0:
                raise MainModelConfigurationError(
                    f"profile {profile_id} resource variant {name}.{key} must be in (0, 1]"
                )
            normalized[key] = cast
        for meta_key in _RESOURCE_VARIANT_METADATA_KEYS & set(spec):
            if not isinstance(spec[meta_key], str) or not spec[meta_key].strip():
                raise MainModelConfigurationError(
                    f"profile {profile_id} resource variant {name}.{meta_key} must be a "
                    "non-empty string"
                )
        parsed[name] = normalized
    return parsed


def _apply_resource_variant(command: list[str], overrides: dict[str, Any]) -> list[str]:
    """선택된 resource variant를 runtime command에 반영한다."""
    out = list(command)
    for key, value in overrides.items():
        flag, _ = _RESOURCE_VARIANT_FLAGS[key]
        rendered = f"{value:g}" if isinstance(value, float) else str(value)
        if flag in out:
            out[out.index(flag) + 1] = rendered
        else:
            out.extend([flag, rendered])
    return out


def _apply_util_override(command: list[str], override: float | None) -> list[str]:
    """호스트별 override가 반영된 ``--gpu-memory-utilization`` 명령을 반환한다."""
    if override is None:
        return command
    rendered = f"{override:g}"
    if "--gpu-memory-utilization" in command:
        out = list(command)
        out[out.index("--gpu-memory-utilization") + 1] = rendered
        return out
    return [*command, "--gpu-memory-utilization", rendered]


def _resolve_profile_image(
    profile_image: object,
    shared_image: str | None,
    env: dict[str, str] | None,
    profile_id: str,
) -> str:
    """프로필 runtime image를 불변 참조로 해석한다.

    - ``None`` inherits the shared ``runtime.image``.
    - ``"${VAR}"`` is resolved from ``env`` (set by CI/deploy, like compose's
      ``${MAIN_MODEL_VLLM_IMAGE_OVERRIDE}``). When ``VAR`` is unset/empty the profile override is not built yet,
      so the profile inherits the shared base only to keep Runtime Controller booting; the
      profile's declared capabilities are unchanged (it is a multimodal model, not a
      separate text-only one), and the switch-time boot canary is what proves the live
      runtime can actually serve them — a switch to a not-yet-built runtime fails the
      canary and rolls back, so the model is never half-served.
    - Registry images use ``name@sha256:...``. A locally built image may use its
      Docker content-addressed ``sha256:...`` image ID. Mutable tags are rejected.
    """
    if profile_image is None:
        if shared_image is not None:
            return shared_image
        raise MainModelConfigurationError(f"profile {profile_id} image is required")
    if isinstance(profile_image, str):
        ref = _IMAGE_ENV_REF_RE.match(profile_image)
        if ref is not None:
            # 호출자가 env를 명시하지 않은 CLI/test 유틸리티도 Compose와 같은
            # process environment를 해석한다. 명시 env={}는 의도적으로 빈 환경이다.
            environment = os.environ if env is None else env
            resolved = environment.get(ref.group(1), "").strip()
            if not resolved and shared_image is not None:
                return shared_image
            if not resolved:
                raise MainModelConfigurationError(
                    f"profile {profile_id} image env {ref.group(1)} is empty"
                )
            if is_immutable_image_ref(resolved):
                return resolved
            raise MainModelConfigurationError(
                f"profile {profile_id} image env {ref.group(1)} must resolve to an immutable "
                "registry digest or local image ID"
            )
        if is_immutable_image_ref(profile_image):
            return profile_image
    raise MainModelConfigurationError(
        f"profile {profile_id} image must be an immutable registry digest, local image ID, "
        "or a ${ENV} reference"
    )


def load_main_model_catalog(
    path: Path,
    *,
    gpu_memory_utilization_override: float | None = None,
    resource_variant: str | None = None,
    env: dict[str, str] | None = None,
    resolve_runtime_images: bool = True,
) -> MainModelCatalog:
    """Main Model catalog를 읽는다.

    Runtime을 생성하거나 관찰하는 호출자는 기본값 그대로, 모든 image 참조가
    실제 digest로 해석된 catalog를 사용해야 한다. 반면 HF cache 준비는 model_id와
    revision만 소비하므로, ``resolve_runtime_images=False``로 image 배포 환경과
    독립적으로 metadata만 읽을 수 있다. 이 모드는 Docker/Compose 경계에 넘기면 안 된다.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise MainModelConfigurationError("main model profile schema version must be 1")
    public_model = str(raw.get("public_model", ""))
    default_profile = str(raw.get("default_profile", ""))
    runtime = raw.get("runtime")
    profiles_raw = raw.get("profiles")
    if not public_model or not isinstance(runtime, dict) or not isinstance(profiles_raw, dict):
        raise MainModelConfigurationError("public_model, runtime, and profiles are required")
    runtime_image = runtime.get("image")
    if not isinstance(runtime_image, str) or not runtime_image.strip():
        raise MainModelConfigurationError("runtime image is required")
    # 공용 runtime image도 profile override와 같은 배포 pin을 사용한다. 이전에는
    # 여기만 과거 literal digest로 남아, image를 따로 선언하지 않은 26B 전환이
    # Docker create의 "No such image"로 실패했다. cache 준비만 이 값을 소비하지
    # 않으므로, 그 경로에서는 env ref를 해석하지 않고 원문을 보존한다.
    image = (
        _resolve_profile_image(runtime_image, None, env, "runtime")
        if resolve_runtime_images
        else runtime_image
    )
    runtime = {**runtime, "image": image}

    profiles: dict[str, MainModelProfile] = {}
    for profile_id, item in profiles_raw.items():
        if not isinstance(item, dict):
            raise MainModelConfigurationError(f"profile {profile_id} must be an object")
        revision = str(item.get("revision", ""))
        if not _REVISION_RE.fullmatch(revision):
            raise MainModelConfigurationError(f"profile {profile_id} revision must be a 40-char commit")
        alias = str(item.get("served_model_name", ""))
        if alias != public_model:
            raise MainModelConfigurationError(
                f"profile {profile_id} served_model_name must remain {public_model}"
            )
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
            raise MainModelConfigurationError(f"profile {profile_id} command must be a string list")
        model_id = str(item.get("model_id", ""))
        if not model_id:
            raise MainModelConfigurationError(f"profile {profile_id} must declare model_id")
        # 모델 신원은 model_id/revision/served_model_name이 소유한다. command는
        # tuning flag만 들고, 실제 argv는 여기서 한 번 조립한다. 같은 값을 YAML에
        # 두 번 적고 대조하던 구조를 없애 둘이 어긋날 여지 자체를 지운다.
        repeated = [flag for flag in _IDENTITY_FLAGS if flag in command]
        if repeated:
            raise MainModelConfigurationError(
                f"profile {profile_id} command must not repeat {repeated}; "
                "model identity comes from model_id/revision/served_model_name"
            )
        command = [
            "--model",
            model_id,
            "--revision",
            revision,
            "--served-model-name",
            public_model,
            *command,
        ]
        # 명시적으로 선택된 resource-policy override를 먼저 반영한다. variant는
        # catalog가 소유한 검토된 자원 정책이고, 그 뒤의 MAIN_MODEL_GPU_MEMORY_UTILIZATION은 단일
        # 호스트용 escape hatch이므로 더 나중에 적용해 항상 마지막 발언권을 갖는다.
        declared_variants = _parse_resource_variants(str(profile_id), item.get("resource_variants"))
        applied_variant: str | None = None
        if resource_variant is not None and resource_variant in declared_variants:
            command = _apply_resource_variant(command, declared_variants[resource_variant])
            applied_variant = resource_variant
        # 호스트별 gpu-memory-utilization 오버라이드가 있으면 적용하여
        # 런타임 커맨드와 파싱된 vram_fraction이 항상 서로 일치하도록 한다.
        command = _apply_util_override(command, gpu_memory_utilization_override)
        resolved_engine_policy = VllmEnginePolicy.from_command(command)
        try:
            profile_state = validate_profile_state(
                str(profile_id),
                item.get("compatibility", {}),
                item.get("qualification"),
            )
        except ValueError as exc:
            raise MainModelConfigurationError(str(exc)) from exc
        capabilities = item.get("capabilities", {"deployed_input": ["text"]})
        if not isinstance(capabilities, dict):
            raise MainModelConfigurationError(f"profile {profile_id} capabilities must be an object")
        unknown_capability_keys = set(capabilities) - _ALLOWED_CAPABILITY_KEYS
        if unknown_capability_keys:
            raise MainModelConfigurationError(
                f"profile {profile_id} capabilities has unsupported key(s): {sorted(unknown_capability_keys)}"
            )
        deployed_input = capabilities.get("deployed_input")
        if (
            not isinstance(deployed_input, list)
            or not deployed_input
            or not all(isinstance(value, str) for value in deployed_input)
            or "text" not in deployed_input
            or not set(deployed_input) <= _ALLOWED_MODALITIES
        ):
            raise MainModelConfigurationError(
                f"profile {profile_id} capabilities.deployed_input must be a non-empty list including "
                f"text, drawn only from {sorted(_ALLOWED_MODALITIES)}"
            )
        gateway_policy = item.get("gateway_policy", {})
        if not isinstance(gateway_policy, dict):
            raise MainModelConfigurationError(f"profile {profile_id} gateway_policy must be an object")
        # engine 한도와 Gateway admission이 갈라지지 않게 하는 계약은 variant를 적용한
        # 뒤에도 유지되어야 한다. variant가 --max-model-len을 옮기면 Gateway의 선제
        # 검사도 같은 값으로 따라간다. 여기서 투영하지 않으면 Gateway가 engine이 곧바로
        # 거부할 요청을 통과시키거나, 반대로 서빙 가능한 요청을 막는다.
        if applied_variant is not None and "--max-model-len" in command:
            variant_max_model_len = int(command[command.index("--max-model-len") + 1])
            request_limits = gateway_policy.get("request_limits")
            if isinstance(request_limits, dict) and "max_model_len" in request_limits:
                gateway_policy = {
                    **gateway_policy,
                    "request_limits": {
                        **request_limits,
                        "max_model_len": variant_max_model_len,
                    },
                }
        # 이전 catalog 형식은 image/boot resolution만 시험하는 최소 Profile을 허용했다.
        # 실제 배포 catalog의 정책 존재는 governance validation에서 강제한다.
        if gateway_policy:
            request_limits = gateway_policy.get("request_limits")
            if not isinstance(request_limits, dict):
                raise MainModelConfigurationError(f"profile {profile_id} gateway_policy.request_limits must be an object")
            if request_limits.get("input_modalities") != deployed_input:
                raise MainModelConfigurationError(
                    f"profile {profile_id} gateway_policy.request_limits.input_modalities must match capabilities.deployed_input"
                )
            if not isinstance(gateway_policy.get("request_parameter_policy"), dict):
                raise MainModelConfigurationError(
                    f"profile {profile_id} gateway_policy.request_parameter_policy must be an object"
                )
            try:
                if int(gateway_policy.get("max_output_tokens", 0)) <= 0:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise MainModelConfigurationError(
                    f"profile {profile_id} gateway_policy.max_output_tokens must be a positive integer"
                ) from exc
        # 프로필은 자체 런타임 이미지(예: multimodal 빌드)를 리터럴 digest나 CI/deploy가
        # resolve하는 ${ENV} 참조로 고정할 수 있다; 지정하지 않으면 공유된 runtime.image를
        # 상속한다. runtime 소비 경로에서는 반드시 digest로 해석한다. cache 준비는
        # model/revision만 사용하므로 image ref를 그대로 두어 배포 env에 의존하지 않는다.
        profile_image = item.get("image")
        if profile_image is not None and (not isinstance(profile_image, str) or not profile_image.strip()):
            raise MainModelConfigurationError(f"profile {profile_id} image must be a non-empty string")
        resolved_image = (
            _resolve_profile_image(profile_image, image, env, str(profile_id))
            if resolve_runtime_images
            else (profile_image or image)
        )
        profiles[str(profile_id)] = MainModelProfile(
            profile_id=str(profile_id),
            display_name=str(item.get("display_name", profile_id)),
            model_id=model_id,
            revision=revision,
            served_model_name=alias,
            command=tuple(command),
            compatibility=dict(profile_state.compatibility),
            qualification=dict(profile_state.qualification),
            capabilities=dict(capabilities),
            gateway_policy=dict(gateway_policy),
            image=resolved_image,
            resolved_engine_policy=resolved_engine_policy,
            resource_variant=applied_variant,
            resource_variants=tuple(sorted(declared_variants)),
        )
    # 운영자가 명시적으로 고른 override를 아무 profile도 선언하지 않았다면
    # 오타이거나 잘못된 host 설정이다. 이 검사는 새 GPU 제품을 거부하는 allowlist가
    # 아니라, 선택한 override가 적용되지 않은 채 reference 정책으로 조용히
    # fallback하는 것을 막는 설정 안전장치다.
    if resource_variant is not None and not any(
        resource_variant in profile.resource_variants for profile in profiles.values()
    ):
        declared = sorted({v for profile in profiles.values() for v in profile.resource_variants})
        raise MainModelConfigurationError(
            f"{RESOURCE_VARIANT_ENV}={resource_variant} is not declared by any profile; "
            f"declared variants: {declared or 'none'}"
        )
    if default_profile not in profiles:
        raise MainModelConfigurationError("default_profile must reference a configured profile")
    return MainModelCatalog(
        public_model, default_profile, dict(runtime), profiles, resource_variant
    )


def resolve_boot_profile(
    catalog: MainModelCatalog,
    *,
    configured_profile: str | None,
    locked: bool,
    persisted_profile: str | None,
) -> str:
    configured = configured_profile or catalog.default_profile
    if configured not in catalog.profiles:
        raise MainModelConfigurationError(f"unknown MAIN_MODEL_BOOT_PROFILE: {configured}")

    def _require_selected_resource_policy(profile_id: str, label: str) -> None:
        missing_policy = catalog.missing_selected_resource_policy(profile_id)
        if missing_policy is not None:
            raise MainModelConfigurationError(
                f"{label} {profile_id} does not declare the explicitly selected "
                f"resource policy override {missing_policy}; refusing reference-policy fallback"
            )

    if locked:
        _require_selected_resource_policy(configured, "MAIN_MODEL_BOOT_PROFILE")
        return configured
    if persisted_profile:
        if persisted_profile not in catalog.profiles:
            raise MainModelConfigurationError(
                f"persisted active profile is not configured: {persisted_profile}"
            )
        _require_selected_resource_policy(persisted_profile, "persisted active profile")
        return persisted_profile
    _require_selected_resource_policy(configured, "MAIN_MODEL_BOOT_PROFILE")
    return configured


