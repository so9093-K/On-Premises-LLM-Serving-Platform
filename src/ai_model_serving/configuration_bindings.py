from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ConfigurationProjection = Callable[[Any], Any]


@dataclass(frozen=True)
class ConfigurationBinding:
    """하나의 Schema Projection ID에 대응하는 코드 소유의 값 출처·노출 연결.

    표시 및 정책 메타데이터는 YAML이 소유한다. 이 Registry는 실행 경계를
    소유한다. Projection이 해석된 설정을 읽는 방식, 운영자 제어 Runtime 값의
    저장소 기본값 출처, 실제 값이 투영될 Runtime Snapshot 필드를 정의한다.
    """

    projection: ConfigurationProjection
    repository_path: tuple[str, ...] | None = None
    runtime_field: str | None = None


CONFIGURATION_BINDINGS: dict[str, ConfigurationBinding] = {
    "deployment_target": ConfigurationBinding(
        projection=lambda settings: settings.deployment_target.target_id,
    ),
    "deployment_control_mode": ConfigurationBinding(
        projection=lambda settings: settings.deployment_target.control_mode,
    ),
    "deployment_lifecycle_owner": ConfigurationBinding(
        projection=lambda settings: settings.deployment_target.lifecycle_owner,
    ),
    "deployment_features": ConfigurationBinding(
        projection=lambda settings: settings.deployment_target.features,
    ),
    "security_auth_mode": ConfigurationBinding(
        projection=lambda settings: settings.security.auth_mode,
    ),
    "security_api_keys": ConfigurationBinding(
        projection=lambda settings: settings.security.api_keys,
    ),
    "main_llm_base_url": ConfigurationBinding(
        projection=lambda settings: settings.runtime("main_llm").base_url,
    ),
    "required_runtime_keys": ConfigurationBinding(
        projection=lambda settings: settings.required_runtime_keys,
    ),
    "max_retrieval_documents": ConfigurationBinding(
        projection=lambda settings: settings.max_retrieval_documents,
        repository_path=("operational_limits", "max_retrieval_documents"),
        runtime_field="max_retrieval_documents",
    ),
    "streaming_max_duration_seconds": ConfigurationBinding(
        projection=lambda settings: settings.streaming_max_duration_seconds,
        repository_path=("streaming", "max_duration_seconds"),
        runtime_field="streaming_max_duration_seconds",
    ),
    "streaming_max_chunks": ConfigurationBinding(
        projection=lambda settings: settings.streaming_max_chunks,
        repository_path=("streaming", "max_chunks"),
        runtime_field="streaming_max_chunks",
    ),
    "streaming_max_bytes": ConfigurationBinding(
        projection=lambda settings: settings.streaming_max_bytes,
        repository_path=("streaming", "max_bytes"),
        runtime_field="streaming_max_bytes",
    ),
}

CONFIGURATION_PROJECTION_IDS = frozenset(CONFIGURATION_BINDINGS)


def binding_for_projection(projection_id: str) -> ConfigurationBinding:
    try:
        return CONFIGURATION_BINDINGS[projection_id]
    except KeyError as exc:
        raise ValueError(f"unknown Configuration Plane projection: {projection_id!r}") from exc


def operator_runtime_bindings(
    schema_items: list[dict[str, Any]],
) -> dict[str, ConfigurationBinding]:
    """검증된 Schema 메타데이터에서 운영자 Runtime 연결 정보를 도출한다.

    운영자가 변경할 수 있는 설정 키는 Schema가 결정한다. 이 Registry는
    해당 Projection ID를 저장소·Runtime 상태로 연결하는 방법을 소유한다.
    동일한 키 목록을 이곳에 중복으로 유지하지 않는다.
    """

    bindings: dict[str, ConfigurationBinding] = {}
    for item in schema_items:
        if item.get("owner") != "operator" or item.get("control_surface") != "configuration":
            continue
        key = str(item["key"])
        binding = binding_for_projection(str(item["projection"]))
        if binding.repository_path is None or binding.runtime_field is None:
            raise ValueError(
                f"operator configuration projection lacks runtime binding: {item['projection']!r}"
            )
        bindings[key] = binding
    return bindings
