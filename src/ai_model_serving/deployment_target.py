from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .configuration import load_yaml_mapping
from .deployment_target_state import validate_deployment_target_state


KNOWN_FEATURES = frozenset(
    {
        "chat",
        "embeddings",
        "retrieval",
        "risk",
        "prompt_detection",
        "runtime_control",
        "model_switching",
        "gpu_admission",
    }
)
_CONTROL_MODES = frozenset({"runtime_controller", "static", "managed_cpu"})
_LIFECYCLE_OWNERS = frozenset({"platform", "external"})
_TARGET_FIELDS = frozenset(
    {
        "display_name",
        "platform",
        "runtime_backend",
        "runs_monitoring_stack",
        "main_profile_catalog",
        "control_mode",
        "lifecycle_owner",
        "internal_service_token_required",
        "implementation_status",
        "qualification_status",
        "features",
        "compose_files",
        "gateway_runtime_host",
    }
)


@dataclass(frozen=True)
class DeploymentTarget:
    target_id: str
    display_name: str
    platform: str
    runtime_backend: str
    runs_monitoring_stack: bool
    main_profile_catalog: str | None
    control_mode: str
    lifecycle_owner: str
    internal_service_token_required: bool
    implementation_status: str
    qualification_status: str
    features: frozenset[str]
    compose_files: tuple[str, ...]
    gateway_runtime_host: str | None

    def supports(self, feature: str) -> bool:
        return feature in self.features

    @property
    def static_serving(self) -> bool:
        """Gateway의 고정 endpoint 여부. Runtime 관리 권한과 독립된 개념이다."""
        return self.control_mode in ("static", "managed_cpu")

    @property
    def adaptive(self) -> bool:
        return self.runtime_backend == "adaptive"

    @property
    def controllable(self) -> bool:
        return self.control_mode == "runtime_controller" and self.lifecycle_owner == "platform"


def load_deployment_target(path: Path, target_id: str | None = None) -> DeploymentTarget:
    document = load_yaml_mapping(path)
    selected = target_id or str(document.get("default_target", ""))
    targets = document.get("targets")
    if not isinstance(targets, dict) or not selected:
        raise RuntimeError(f"deployment target catalog is invalid: {path}")
    raw = targets.get(selected)
    if not isinstance(raw, dict):
        allowed = ", ".join(sorted(str(item) for item in targets))
        raise RuntimeError(f"unknown DEPLOYMENT_TARGET {selected!r}; allowed: {allowed}")

    unknown_fields = set(raw) - _TARGET_FIELDS
    if unknown_fields:
        raise RuntimeError(
            f"deployment target {selected!r} has unknown fields: "
            f"{', '.join(sorted(unknown_fields))}"
        )

    control_mode = str(raw.get("control_mode", ""))
    lifecycle_owner = str(raw.get("lifecycle_owner", ""))
    runs_monitoring_stack = raw.get("runs_monitoring_stack")
    internal_service_token_required = raw.get("internal_service_token_required")
    try:
        target_state = validate_deployment_target_state(selected, raw)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    raw_features: Any = raw.get("features")
    if control_mode not in _CONTROL_MODES:
        raise RuntimeError(f"deployment target {selected!r} has invalid control_mode {control_mode!r}")
    if lifecycle_owner not in _LIFECYCLE_OWNERS:
        raise RuntimeError(
            f"deployment target {selected!r} has invalid lifecycle_owner {lifecycle_owner!r}"
        )
    if not isinstance(runs_monitoring_stack, bool):
        raise RuntimeError(
            f"deployment target {selected!r} runs_monitoring_stack must be boolean"
        )
    if not isinstance(internal_service_token_required, bool):
        raise RuntimeError(
            f"deployment target {selected!r} internal_service_token_required must be boolean"
        )
    if not isinstance(raw_features, dict):
        raise RuntimeError(f"deployment target {selected!r} features must be a mapping")
    unknown_features = set(raw_features) - KNOWN_FEATURES
    if unknown_features:
        raise RuntimeError(
            f"deployment target {selected!r} has unknown features: {', '.join(sorted(unknown_features))}"
        )
    non_boolean_features = [
        str(key) for key, enabled in raw_features.items() if not isinstance(enabled, bool)
    ]
    if non_boolean_features:
        raise RuntimeError(
            f"deployment target {selected!r} has non-boolean features: "
            f"{', '.join(sorted(non_boolean_features))}"
        )
    platform = str(raw.get("platform", "")).strip()
    runtime_backend = str(raw.get("runtime_backend", "")).strip()
    main_profile_catalog = str(raw.get("main_profile_catalog", "")).strip() or None
    if not platform or not runtime_backend:
        raise RuntimeError(
            f"deployment target {selected!r} requires platform and runtime_backend"
        )
    if raw_features.get("chat") is True and not main_profile_catalog:
        raise RuntimeError(f"deployment target {selected!r} with chat requires main_profile_catalog")
    if main_profile_catalog and (
        Path(main_profile_catalog).is_absolute() or ".." in Path(main_profile_catalog).parts
    ):
        raise RuntimeError(
            f"deployment target {selected!r} main_profile_catalog must be a safe relative path"
        )
    # Static·Adaptive 진입점과 노출 진단은 같은 Compose 목록을 사용한다.
    # GPU Dynamic 진입점은 실행 시 override를 조합한다.
    raw_compose_files = raw.get("compose_files")
    if control_mode in ("static", "managed_cpu") or runtime_backend == "adaptive":
        if not isinstance(raw_compose_files, list) or not raw_compose_files:
            raise RuntimeError(
                f"deployment target {selected!r} requires a non-empty compose_files list"
            )
    elif raw_compose_files is not None:
        raise RuntimeError(
            f"deployment target {selected!r} must not declare compose_files; "
            "only static and adaptive targets consume it"
        )
    compose_files: list[str] = []
    for entry in raw_compose_files or []:
        if not isinstance(entry, str) or not entry.strip():
            raise RuntimeError(f"deployment target {selected!r} compose_files entries must be paths")
        entry_path = Path(entry.strip())
        if entry_path.is_absolute() or ".." in entry_path.parts:
            raise RuntimeError(
                f"deployment target {selected!r} compose_files entries must be safe relative paths"
            )
        compose_files.append(entry.strip())
    gateway_runtime_host_raw = raw.get("gateway_runtime_host")
    gateway_runtime_host = None
    if gateway_runtime_host_raw is not None:
        gateway_runtime_host = str(gateway_runtime_host_raw).strip()
        if not gateway_runtime_host or "://" in gateway_runtime_host or "/" in gateway_runtime_host:
            raise RuntimeError(
                f"deployment target {selected!r} gateway_runtime_host must be a host name"
            )
        if control_mode not in ("static", "managed_cpu"):
            raise RuntimeError(
                f"deployment target {selected!r} gateway_runtime_host is only valid for static targets"
            )

    expected_owner = "platform" if control_mode in ("runtime_controller", "managed_cpu") else "external"
    if control_mode == "managed_cpu" and (runtime_backend != "llama-cpp" or platform != "linux"):
        raise RuntimeError("managed_cpu requires linux and llama-cpp backend")
    if lifecycle_owner != expected_owner:
        raise RuntimeError(
            f"deployment target {selected!r} control_mode={control_mode!r} requires "
            f"lifecycle_owner={expected_owner!r}"
        )
    features = frozenset(str(key) for key, enabled in raw_features.items() if enabled is True)
    if "chat" not in features:
        if runtime_backend != "none" or control_mode != "static" or main_profile_catalog is not None:
            raise RuntimeError(
                f"deployment target {selected!r} without chat must be static, "
                "use runtime_backend=none and omit main_profile_catalog"
            )
    if "retrieval" in features and "embeddings" not in features:
        raise RuntimeError(f"deployment target {selected!r}: retrieval requires embeddings")
    if "prompt_detection" in features and "risk" not in features:
        raise RuntimeError(
            f"deployment target {selected!r}: prompt_detection requires risk"
        )
    lifecycle_flags = [
        feature in features
        for feature in ("runtime_control", "model_switching", "gpu_admission")
    ]
    if len(set(lifecycle_flags)) != 1:
        raise RuntimeError(
            f"deployment target {selected!r} must enable or disable runtime_control, "
            "model_switching, and gpu_admission together"
        )
    if control_mode in ("static", "managed_cpu") and ({"runtime_control", "model_switching", "gpu_admission"} & features):
        raise RuntimeError(f"static deployment target {selected!r} cannot enable lifecycle control features")

    return DeploymentTarget(
        target_id=selected,
        display_name=str(raw.get("display_name", selected)),
        platform=platform,
        runtime_backend=runtime_backend,
        runs_monitoring_stack=runs_monitoring_stack,
        main_profile_catalog=main_profile_catalog,
        control_mode=control_mode,
        lifecycle_owner=lifecycle_owner,
        internal_service_token_required=internal_service_token_required,
        implementation_status=target_state.implementation_status,
        qualification_status=target_state.qualification_status,
        features=features,
        compose_files=tuple(compose_files),
        gateway_runtime_host=gateway_runtime_host,
    )
