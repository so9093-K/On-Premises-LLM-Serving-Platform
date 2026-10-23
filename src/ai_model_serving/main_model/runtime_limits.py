"""운영자의 서버 토큰 한도 선택을 불변 모델 프로필의 실행 변형으로 해석한다.

임의 command/image 선택은 허용하지 않는다. 실제 정책 적용은 MainModelManager의
기존 drain/replace/canary/rollback 경로만 소유한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from .catalog import MainModelCatalog, MainModelProfile
from .engine_policy import CpuEnginePolicy, VllmEnginePolicy


class RuntimeLimitError(ValueError):
    pass


def _checked_int(value: object, key: str) -> int:
    if type(value) is not int or value <= 0:
        raise RuntimeLimitError(f"{key} must be a positive integer")
    return value


def _limit_from_profile(profile: MainModelProfile) -> int:
    raw = profile.gateway_policy.get("request_limits", {}).get("max_model_len")
    return _checked_int(raw, "profile max_model_len")


def override_profile_id(base_id: str, context_tokens: int, max_output_tokens: int) -> str:
    raw = json.dumps([base_id, context_tokens, max_output_tokens], separators=(",", ":"))
    return "limits-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _set_flag(command: tuple[str, ...], flag: str, value: int) -> tuple[str, ...]:
    if command.count(flag) != 1:
        raise RuntimeLimitError(f"declared runtime does not support changing {flag}")
    values = list(command)
    index = values.index(flag)
    if index + 1 >= len(values):
        raise RuntimeLimitError(f"missing declared value for {flag}")
    values[index + 1] = str(value)
    return tuple(values)


def build_runtime_limit_profile(
    catalog: MainModelCatalog,
    base_profile_id: str,
    context_tokens: object,
    max_output_tokens: object,
) -> MainModelProfile:
    base = catalog.profiles.get(base_profile_id)
    if base is None or base_profile_id.startswith("limits-"):
        raise RuntimeLimitError("base profile must be a declared runtime profile")
    if base.runtime_backend not in {"llama-cpp", "vllm-cuda"}:
        raise RuntimeLimitError("runtime token editing is only supported for managed CPU/GPU")
    context = _checked_int(context_tokens, "context_tokens")
    output = _checked_int(max_output_tokens, "max_output_tokens")
    if output > context:
        raise RuntimeLimitError("max_output_tokens must not exceed context_tokens")
    base_context = _limit_from_profile(base)
    if base.runtime_backend == "llama-cpp":
        declared_max = max(
            _limit_from_profile(p)
            for p in catalog.profiles.values()
            if not p.profile_id.startswith("limits-")
            and p.runtime_backend == "llama-cpp"
            and p.model_id == base.model_id and p.revision == base.revision
        )
        # 미검증 장문맥의 무제한 확장을 허용하지 않는다. 기존 선언된 최대 CPU
        # 프리셋을 안전 경계로 삼고 실제 RAM/지연은 전환 시 검증한다.
        if context < 512 or context > declared_max:
            raise RuntimeLimitError(f"CPU context_tokens must be in 512..{declared_max}")
        command = _set_flag(base.command, "--ctx-size", context)
        engine = CpuEnginePolicy(context, base.resolved_engine_policy.max_num_seqs)
    else:
        # GPU는 선언된 기준 정책보다 문맥을 늘리면 KV 캐시·VRAM admission이
        # 달라진다. 별도 호스트 자원 검증 없는 상향 조정은 허용하지 않는다.
        if context < 1024 or context > base_context:
            raise RuntimeLimitError(f"GPU context_tokens must be in 1024..{base_context}")
        command = _set_flag(base.command, "--max-model-len", context)
        engine = VllmEnginePolicy.from_command(command)
    policy = {
        **base.gateway_policy,
        "max_output_tokens": output,
        "request_limits": {
            **base.gateway_policy.get("request_limits", {}),
            "max_model_len": context,
        },
    }
    return replace(
        base,
        profile_id=override_profile_id(base_profile_id, context, output),
        display_name=f"{base.display_name} · 사용자 한도 {context}/{output}",
        command=command,
        gateway_policy=policy,
        resolved_engine_policy=engine,
        qualification={**base.qualification, "status": "unverified"},
    )


def restore_runtime_limit_profiles(catalog: MainModelCatalog, records: object) -> None:
    """지속 상태의 한도를 다시 구성하고 파생 프로필과 실행 command를 검증한다."""
    if records is None:
        return
    if not isinstance(records, dict) or len(records) > 32:
        raise RuntimeLimitError("invalid persisted runtime token limits")
    for profile_id, entry in records.items():
        if not isinstance(entry, dict) or set(entry) != {"base_profile", "context_tokens", "max_output_tokens"}:
            raise RuntimeLimitError("invalid persisted runtime limit entry")
        derived = build_runtime_limit_profile(
            catalog, entry["base_profile"], entry["context_tokens"], entry["max_output_tokens"],
        )
        if profile_id != derived.profile_id or profile_id in catalog.profiles:
            raise RuntimeLimitError("persisted runtime limit profile identity mismatch")
        catalog.profiles[profile_id] = derived
