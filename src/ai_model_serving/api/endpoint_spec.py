from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..detectors.pii import LABELS_BY_CODE as _PII_LABELS_BY_CODE
from ..detectors.secret import LABELS_BY_CODE as _SECRET_LABELS_BY_CODE

# D-code의 사람이 읽을 이름. 코드 자체의 유효 집합은 contracts/risk.py가 갖는다.
_CODE_TITLES: dict[str, str] = {
    "D1": "개인 식별자",
    "D2": "연락처",
    "D4": "시크릿·자격증명",
    "D5": "네트워크·인프라",
}


def _detected_codes_block(labels_by_code: dict[str, tuple[str, ...]]) -> str:
    """탐지기가 실제로 내보내는 라벨 목록에서 문서의 코드 표를 만든다.

    예전에는 이 목록을 설명 문자열에 손으로 적어두고 gateway/risk-signal-service 두
    군데에 복사해뒀다. 그래서 ANTHROPIC_API_KEY가 추가됐을 때 네 곳이 그대로
    뒤처졌고, OpenAPI 스냅샷 비교는 description을 보지 않아 아무도 몰랐다.
    """
    return "".join(
        f"- **{code}** {_CODE_TITLES[code]}: {', '.join(labels)}\n"
        for code, labels in sorted(labels_by_code.items())
    )


_PII_DETECTOR_DESCRIPTION = (
    "**PII Protection 탐지기** — 한국형 식별자·이메일·전화번호·카드번호·IP를 정규식으로 직접 탐지합니다.\n\n"
    "탐지 코드:\n"
    + _detected_codes_block(_PII_LABELS_BY_CODE)
    + "\n원문 PII 값은 응답에 포함되지 않습니다. `span_count`로 entity별 탐지 개수를 제공합니다.\n"
    "탐지 결과는 최종 정책 판단이 아니라 진단용 신호로 다뤄야 합니다."
)

_SECRET_DETECTOR_DESCRIPTION = (
    "**Secret Exposure 탐지기** — 정제한 정규식과 엔트로피로 직접 탐지합니다. 외부 도구 없이 프로세스 안에서 동작합니다.\n\n"
    "탐지 코드:\n"
    + _detected_codes_block(_SECRET_LABELS_BY_CODE)
    + "\n응답·로그·지표 라벨 어디에도 원문 시크릿을 남기지 않습니다. 탐지 개수는 `span_count`로 알려줍니다.\n"
    "탐지 결과는 최종 정책 판단이 아니라 진단용 신호로 다뤄야 합니다."
)


@dataclass(frozen=True)
class EndpointSpec:
    method: str         # "GET" | "POST"
    path: str
    operation_id: str
    tag: str            # OpenAPI 태그 이름
    summary: str
    description: str
    request_schema: str | None       # 예: "chat_completion_request.schema.json"
    response_schema: str | None      # 예: "chat_completion_response.schema.json"
    # 이 endpoint에서만 발생하는 공개 오류. 모든 JSON write에 공통인 인증·크기·
    # 입력 검증·내부 오류는 WRITE_BASE_ERROR_CODES에서 합쳐진다.
    error_codes: tuple[str, ...] = ()

RouteKey = tuple[str, str]  # (method, path)

WRITE_BASE_ERROR_CODES = (
    "UNAUTHORIZED",
    "REQUEST_TOO_LARGE",
    "VALIDATION_ERROR",
    "INTERNAL_ERROR",
)
UPSTREAM_ERROR_CODES = (
    "RATE_LIMITED",
    "QUEUE_TIMEOUT",
    "CIRCUIT_OPEN",
    "UPSTREAM_TIMEOUT",
    "UPSTREAM_ERROR",
    "UPSTREAM_RESPONSE_INVALID",
)


def schema_maps_from_specs(
    endpoints: Sequence[EndpointSpec],
) -> tuple[dict[RouteKey, str], dict[RouteKey, str]]:
    """EndpointSpec 목록에서 요청·응답 스키마 매핑을 파생한다."""
    request_schemas: dict[RouteKey, str] = {
        (s.method, s.path): s.request_schema
        for s in endpoints
        if s.request_schema is not None
    }
    response_schemas: dict[RouteKey, str] = {
        (s.method, s.path): s.response_schema
        for s in endpoints
        if s.response_schema is not None
    }
    return request_schemas, response_schemas


def error_codes_from_specs(endpoints: Sequence[EndpointSpec]) -> dict[RouteKey, tuple[str, ...]]:
    """Endpoint별 공개 오류 목록을 공통 HTTP 경계와 합쳐 반환한다.

    인증이 실제로 적용되는지는 path 이름이 아니라 FastAPI가 생성한
    operation.security가 소유한다. 따라서 여기서는 401 후보를 제공하고,
    인증이 비활성이거나 공개 endpoint인 경우는 OpenAPI 투영 단계가 제외한다.
    """
    result: dict[RouteKey, tuple[str, ...]] = {}
    for spec in endpoints:
        if spec.method in {"POST", "PUT", "PATCH"}:
            base = WRITE_BASE_ERROR_CODES
        else:
            base = ("UNAUTHORIZED",)
        codes = tuple(dict.fromkeys((*base, *spec.error_codes)))
        if codes:
            result[(spec.method, spec.path)] = codes
    return result


# ---------------------------------------------------------------------------
# Gateway 엔드포인트 (port 9600)
# ---------------------------------------------------------------------------

GATEWAY_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        method="GET",
        path="/health",
        operation_id="getGatewayHealth",
        tag="Operations",
        summary="프로세스 상태 확인",
        description="프로세스가 살아 있는지만 확인합니다. 항상 HTTP 200을 반환하며 인증 없이 호출할 수 있습니다.",
        request_schema=None,
        response_schema=None,
    ),
    EndpointSpec(
        method="GET",
        path="/ready",
        operation_id="getGatewayReadiness",
        tag="Operations",
        summary="서비스 준비 상태 확인",
        description=(
            "현재 배포의 필수 런타임과 Risk Signal Service가 요청을 받을 준비가 됐는지 확인합니다. "
            "필수 의존 서비스가 준비되지 않으면 HTTP 503을 반환합니다. "
            "`required_not_ready_dependencies`와 `optional_not_ready_dependencies`에서 필수·선택 의존 서비스의 상태를 구분하세요."
        ),
        request_schema=None,
        response_schema="readiness_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/metrics",
        operation_id="getGatewayMetrics",
        tag="Monitoring",
        summary="Prometheus 지표 조회",
        description="Prometheus 형식의 Gateway 지표를 반환합니다. 관리자 인증 설정을 따릅니다.",
        request_schema=None,
        response_schema=None,
    ),
    EndpointSpec(
        method="GET",
        path="/admin/control-plane/bootstrap",
        operation_id="getControlPlaneBootstrap",
        tag="Operations",
        summary="Control Plane 접속 정보 조회",
        description=(
            "Control Plane 접속에 필요한 배포 환경·인증 요구 여부·지원 기능을 반환합니다. 인증 전에도 조회할 수 있으며 API 키·내부 주소·호스트 경로는 포함하지 않습니다."
        ),
        request_schema=None,
        response_schema="control_plane_bootstrap_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/admin/traffic/recent",
        operation_id="getRecentTraffic",
        tag="Operations",
        summary="최근 공개 API 트래픽 요약 조회",
        description=(
            (
            "최근 공개 API(`/v1/*`) 요청 결과와 지연 시간 요약입니다. 기본 집계 구간은 5분이며 Gateway 재시작 시 초기화됩니다. 장기 추세는 Prometheus·Grafana에서 확인하세요.\n"
            "\n"
            "`completion_latency_seconds`는 비스트리밍 Chat Completions·Responses의 런타임 완료 시간, `time_to_first_chunk_seconds`는 스트리밍 첫 청크까지의 시간입니다. 백분위는 보간 없는 nearest-rank 방식이며 `minimum_samples`보다 표본이 적으면 `null`입니다."
        )
        ),
        request_schema=None,
        response_schema="recent_traffic_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/admin/config/schema",
        operation_id="getConfigurationSchema",
        tag="Operations",
        summary="설정 항목 정의 조회",
        description=(
            "설정 항목의 이름·허용값·소유자·민감도·적용 방식을 반환합니다. 운영자 소유 항목 중 `editable=true`인 항목만 변경할 수 있습니다."
        ),
        request_schema=None,
        response_schema="configuration_schema_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/admin/config/effective",
        operation_id="getEffectiveConfiguration",
        tag="Operations",
        summary="현재 적용된 설정 조회",
        description=(
            "현재 적용된 설정값과 출처를 반환합니다. 시크릿 원문은 반환하지 않습니다. 변경 계획과 적용에는 응답의 `revision`과 HTTP `ETag`를 사용하세요."
        ),
        request_schema=None,
        response_schema="configuration_effective_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/admin/config/history",
        operation_id="listConfigurationHistory",
        tag="Operations",
        summary="설정 변경 이력 조회",
        description=(
            "설정 변경 이력을 최신 순서로 반환합니다. 다음 페이지는 `cursor`로 조회하세요. 내부 복구 스냅샷과 원시 오류 문자열은 포함하지 않습니다."
        ),
        request_schema=None,
        response_schema="configuration_history_response.schema.json",
        error_codes=(
            "VALIDATION_ERROR",
            "CONFIGURATION_WRITE_UNAVAILABLE",
        ),
    ),
    EndpointSpec(
        method="POST",
        path="/admin/config/rollbacks/plans",
        operation_id="planConfigurationRollback",
        tag="Operations",
        summary="설정 복구 계획 검토",
        description=(
            "과거 리비전의 운영자 설정으로 복구할 때 필요한 변경과 영향을 계산합니다. 현재 기본 설정과 우선순위를 적용해 다시 계산하며 실제 설정은 변경하지 않습니다."
        ),
        request_schema="configuration_rollback_plan_request.schema.json",
        response_schema="configuration_rollback_plan_response.schema.json",
        error_codes=(
            "CONFIG_REVISION_CONFLICT",
            "CONFIGURATION_WRITE_UNAVAILABLE",
        ),
    ),
    EndpointSpec(
        method="POST",
        path="/admin/config/rollbacks",
        operation_id="applyConfigurationRollback",
        tag="Operations",
        summary="검토한 설정 복구 적용",
        description=(
            "`If-Match: \"config-<revision>\"`과 복구 계획의 `plan_digest`를 함께 보내세요. 복구 성공 시 새 리비전이 생성되며 과거 리비전 번호로 되돌아가지 않습니다."
        ),
        request_schema="configuration_rollback_apply_request.schema.json",
        response_schema="configuration_rollback_apply_response.schema.json",
        error_codes=(
            "PRECONDITION_REQUIRED",
            "CONFIG_REVISION_CONFLICT",
            "CONFIGURATION_WRITE_UNAVAILABLE",
            "CONFIGURATION_APPLY_FAILED",
        ),
    ),
    EndpointSpec(
        method="POST",
        path="/admin/config/plans",
        operation_id="planConfigurationChange",
        tag="Operations",
        summary="설정 변경 계획 검토",
        description=(
            "현재 리비전에서 `set`·`reset`의 유효성과 변경 영향을 검토합니다. 실제 저장 없이 변경 전후 값·적용 방식·위험도·`plan_digest`를 반환합니다. 적용할 때 같은 변경 내용과 다이제스트를 사용하세요."
        ),
        request_schema="configuration_plan_request.schema.json",
        response_schema="configuration_plan_response.schema.json",
        error_codes=(
            "CONFIG_REVISION_CONFLICT",
            "CONFIGURATION_WRITE_UNAVAILABLE",
        ),
    ),
    EndpointSpec(
        method="PATCH",
        path="/admin/config",
        operation_id="applyConfigurationChange",
        tag="Operations",
        summary="검토한 설정 변경 적용",
        description=(
            "`If-Match: \"config-<revision>\"`과 계획에서 받은 `plan_digest`를 함께 보내세요. 리비전이나 검토한 변경 내용이 달라지면 적용을 거부합니다. 저장 후 같은 리비전이 런타임에 적용됐는지 검증합니다. `reset`은 운영자 재정의를 제거해 다음 우선순위의 값을 사용합니다."
        ),
        request_schema="configuration_apply_request.schema.json",
        response_schema="configuration_apply_response.schema.json",
        error_codes=(
            "PRECONDITION_REQUIRED",
            "CONFIG_REVISION_CONFLICT",
            "CONFIGURATION_WRITE_UNAVAILABLE",
            "CONFIGURATION_APPLY_FAILED",
        ),
    ),
    EndpointSpec(
        method="GET",
        path="/internal/main-model/drain-status",
        operation_id="getMainModelDrainStatus",
        tag="Runtime Control",
        summary="진행 중인 메인 모델 요청 수 조회",
        description=(
            "Runtime Controller가 모델 교체 전에 진행 중인 local-main 요청 수를 확인하는 "
            "내부 서비스 전용 endpoint입니다. OpenAPI UI에는 노출하지 않습니다."
        ),
        request_schema=None,
        response_schema=None,
    ),
    EndpointSpec(
        method="GET",
        path="/v1/models",
        operation_id="listModels",
        tag="Models",
        summary="공개 모델 목록 조회",
        description=(
            "공개 모델 ID·지원 기능·허용 파라미터·입력 한도를 반환합니다. 모델 목록은 런타임의 실행 여부와 별개이며 현재 준비 상태는 `/ready`에서 확인하세요."
        ),
        request_schema=None,
        response_schema="model_list_response.schema.json",
    ),
    EndpointSpec(
        method="POST",
        path="/v1/chat/completions",
        operation_id="createChatCompletion",
        tag="Chat",
        summary="대화 응답 생성",
        description=(
            "`local-main`에 메시지 목록을 보내 대화 응답을 생성합니다. 지원 파라미터와 입력 종류는 활성 메인 모델 프로필에 따라 달라집니다."
        ),
        request_schema="chat_completion_request.schema.json",
        response_schema="chat_completion_response.schema.json",
        error_codes=(
            *UPSTREAM_ERROR_CODES,
            "STRUCTURED_OUTPUT_INVALID",
            "MODEL_CAPABILITY_MISMATCH",
            "MODEL_UNAVAILABLE",
            "MAIN_MODEL_CONTROL_UNAVAILABLE",
            "MAIN_MODEL_SWITCH_IN_PROGRESS",
            "STREAM_LIMIT_EXCEEDED",
            "CONFLICT",
        ),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/responses",
        operation_id="createResponse",
        tag="Responses",
        summary="모델 응답 생성",
        description=(
            (
            "`local-main`에 항목 기반 입력을 보내 응답을 생성합니다. Chat Completions와 같은 활성 메인 모델의 기능·요청 수 제한을 따릅니다.\n"
            "\n"
            "- 대화 이어가기: 이전 `output` 항목과 도구 실행 결과를 다음 요청의 `input`에 포함하세요.\n"
            "- 구조화 출력: `text.format`을 사용하세요.\n"
            "- 추론: 활성 프로필이 지원하는 `reasoning.effort`를 사용하세요.\n"
            "- 스트리밍: `stream: true`로 이벤트 유형별 SSE 응답을 받습니다. `response.completed`, `response.failed`, 오류 이벤트를 확인하세요.\n"
            "\n"
            "서버 응답 저장·`previous_response_id`·백그라운드 실행·서버에서 실행하는 도구는 지원하지 않습니다."
        )
        ),
        request_schema="responses_request.schema.json",
        response_schema="responses_response.schema.json",
        error_codes=(
            *UPSTREAM_ERROR_CODES,
            "STRUCTURED_OUTPUT_INVALID",
            "MODEL_CAPABILITY_MISMATCH",
            "MODEL_UNAVAILABLE",
            "MAIN_MODEL_CONTROL_UNAVAILABLE",
            "MAIN_MODEL_SWITCH_IN_PROGRESS",
            "STREAM_LIMIT_EXCEEDED",
            "CONFLICT",
        ),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/embeddings",
        operation_id="createEmbedding",
        tag="Embeddings",
        summary="텍스트 임베딩 생성",
        description=(
            "`local-embed` 또는 `local-embed-ko`로 텍스트를 벡터로 변환합니다. 미지원 파라미터는 `422 VALIDATION_ERROR`로 거부됩니다."
        ),
        request_schema="embedding_request.schema.json",
        response_schema="embedding_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "MODEL_CAPABILITY_MISMATCH", "MODEL_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/prompt/assessments",
        operation_id="assessPromptRisk",
        tag="Risk",
        summary="프롬프트 공격 신호 탐지",
        description=(
            (
            "Prompt 탐지기(`risk-prompt`)로 프롬프트 인젝션·시스템 프롬프트 유출 신호를 탐지합니다. 지시 무시 유도·역할극 탈옥·문서 내 악성 지시·도구 악용을 다룹니다.\n"
            "\n"
            "최종 허용·차단은 호출 애플리케이션이 결정합니다. 탐지기가 비활성화된 배포에서는 `409 DETECTOR_DISABLED`입니다."
        )
        ),
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "DETECTOR_DISABLED", "MODEL_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/pii/assessments",
        operation_id="assessPIIRisk",
        tag="Risk",
        summary="개인정보 노출 신호 탐지",
        description=_PII_DETECTOR_DESCRIPTION,
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "DETECTOR_DISABLED"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/secret/assessments",
        operation_id="assessSecretRisk",
        tag="Risk",
        summary="시크릿 노출 신호 탐지",
        description=_SECRET_DETECTOR_DESCRIPTION,
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "DETECTOR_DISABLED"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/assessments",
        operation_id="assessRisk",
        tag="Risk",
        summary="위험 신호 통합 탐지",
        description=(
            (
            "배포에서 활성화된 탐지기를 설정된 순서로 실행하고 결과를 통합합니다. 로컬 구성은 PII Protection·Secret Exposure를 실행하며 Prompt 런타임이 활성화된 구성에서 프롬프트 탐지를 추가합니다.\n"
            "\n"
            "하나라도 신호를 탐지하면 `risk_detected: true`입니다. HTTP 200이어도 `status=failed` 또는 `assessment_complete=false`이면 탐지가 완료되지 않은 결과이며 안전 판정으로 사용할 수 없습니다."
        )
        ),
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "DETECTOR_DISABLED", "MODEL_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/retrieval/rerank",
        operation_id="rerankDocuments",
        tag="Retrieval",
        summary="문서 관련도 재순위 정렬",
        description=(
            (
            "`query`와 `documents`의 관련도 점수를 계산해 내림차순으로 반환합니다. `top_n`으로 상위 결과 수(1–32)를 지정합니다.\n"
            "\n"
            "`score_mode`는 `dense_cosine`을 지원합니다. 기본 모델은 `local-embed-ko`이며 `local-embed`도 선택할 수 있습니다."
        )
        ),
        request_schema="retrieval_rerank_request.schema.json",
        response_schema="retrieval_rerank_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "MODEL_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/retrieval/score",
        operation_id="scoreDocuments",
        tag="Retrieval",
        summary="문서 관련도 점수 계산 (입력 순서 유지)",
        description=(
            "`query`와 `documents`의 관련도 점수를 입력 순서대로 반환합니다. `score_mode`는 `dense_cosine`을 지원하며 `top_n`은 지원하지 않습니다. 정렬된 결과가 필요하면 `POST /v1/retrieval/rerank`를 사용하세요."
        ),
        request_schema="retrieval_score_request.schema.json",
        response_schema="retrieval_score_response.schema.json",
        error_codes=(*UPSTREAM_ERROR_CODES, "MODEL_UNAVAILABLE"),
    ),
    # ------------------------------------------------------------------ 관리자 런타임 제어
    EndpointSpec(
        method="GET",
        path="/admin/serving-envelope",
        operation_id="getServingEnvelope",
        tag="Runtime Control",
        summary="모델 서빙 설정 조회",
        description=(
            (
            "메인 모델의 요청 수·대기 시간 제한과 런타임 실행 설정을 조회합니다. 최대 사용자 수나 권장 동시 요청 수를 의미하지 않습니다.\n"
            "\n"
            "동적 배포는 활성 프로필의 설정을, 정적 배포는 선택된 외부 런타임 프로필의 설정을 반환합니다. 정적 배포 응답은 외부 프로세스를 실시간 관측한 값이 아닙니다."
        )
        ),
        request_schema=None,
        response_schema="serving_envelope_response.schema.json",
        error_codes=("MAIN_MODEL_CONTROL_UNAVAILABLE", "MODEL_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/runtimes",
        operation_id="listRuntimes",
        tag="Runtime Control",
        summary="런타임 상태 조회",
        description=(
            (
            "메인 모델과 보조 런타임의 설정 상태·컨테이너 관측 상태·GPU 정책 예약 비율을 조회합니다.\n"
            "\n"
            "- `state`: 설정 상태(`active`, `stopped`, `starting`).\n"
            "- `container_status`: 실제 Docker 컨테이너 상태.\n"
            "- `vram_fraction`: 동시 실행 판단용 GPU 정책 예약 비율. 실측 메모리 사용량이 아닙니다.\n"
            "- `budget`: 정책 예약 상한(`ceiling`)·예약 합계(`used`)·예약 가능 여유(`free`).\n"
            "\n"
            "시작·중지는 변경 계획을 검토한 뒤 `PATCH /admin/runtimes/{service_key}`로 적용합니다. 메인 모델의 키는 `main`이며 프로필 교체는 `POST /admin/main-model/switch`를 사용합니다."
        )
        ),
        request_schema=None,
        response_schema="runtime_list_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/admin/runtimes/operations",
        operation_id="listRuntimeTransitionOperations",
        tag="Runtime Control",
        summary="런타임 상태 전환 이력 조회",
        description=(
            "런타임 시작·중지 이력을 최신 순서로 반환합니다. 각 작업에 실행 주체·요청 ID·검토한 계획의 다이제스트·적용 결과·관측 검증 결과가 포함됩니다."
        ),
        request_schema=None,
        response_schema="runtime_transition_history_response.schema.json",
        error_codes=("VALIDATION_ERROR", "RUNTIME_HISTORY_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/runtimes/operations/{operation_id}",
        operation_id="getRuntimeTransitionOperation",
        tag="Runtime Control",
        summary="런타임 상태 전환 작업 조회",
        description=(
            "런타임 상태 전환 작업의 적용·검증 결과를 조회합니다. 적용 후 목표 상태를 확인하지 못하면 `verification_failed`, 재시작으로 종료 결과를 기록하지 못한 작업은 `interrupted_after_restart`입니다."
        ),
        request_schema=None,
        response_schema="runtime_transition_operation_response.schema.json",
        error_codes=("NOT_FOUND", "RUNTIME_HISTORY_UNAVAILABLE"),
    ),
    EndpointSpec(
        method="POST",
        path="/admin/runtimes/{service_key}/plans",
        operation_id="planRuntimeTransition",
        tag="Runtime Control",
        summary="런타임 상태 전환 계획 검토",
        description=(
            "런타임 변경 전에 GPU 정책 예산·선행 조건·시작 및 중지 대상을 검토합니다. 실제 상태는 변경하지 않습니다. 반환된 `plan_digest`를 같은 변경 내용과 함께 PATCH 요청에 반드시 포함하세요."
        ),
        request_schema="runtime_transition_plan_request.schema.json",
        response_schema="runtime_transition_plan_response.schema.json",
        error_codes=(
            "NOT_FOUND",
            "MAIN_MODEL_CONTROL_UNAVAILABLE",
        ),
    ),
    EndpointSpec(
        method="PATCH",
        path="/admin/runtimes/{service_key}",
        operation_id="transitionRuntime",
        tag="Runtime Control",
        summary="검토한 런타임 상태 전환 적용",
        description=(
            (
            "검토한 계획의 `plan_digest`와 `desired_state`를 보내세요. `service_key`는 런타임 목록의 키를 사용하며 메인 모델은 `main`입니다.\n"
            "\n"
            "- `active`: 런타임을 시작하고 요청 라우팅을 복구합니다.\n"
            "- `stopped`: 런타임을 중지하고 GPU 메모리를 회수합니다.\n"
            "\n"
            "GPU 정책 예산이 부족하면 `409 GPU_BUDGET_EXCEEDED`와 중지 후보를 반환합니다. `force: true`는 낮은 우선순위 보조 런타임의 자동 중지를 허용하므로 변경 계획에서 영향을 먼저 확인하세요. 적용·관측 검증 결과는 런타임 작업 이력에서 조회할 수 있습니다."
        )
        ),
        request_schema="runtime_transition_apply_request.schema.json",
        response_schema="runtime_transition_apply_response.schema.json",
        error_codes=(
            "NOT_FOUND",
            "CONFLICT",
            "GPU_BUDGET_EXCEEDED",
            "MODEL_UNAVAILABLE",
            "MAIN_MODEL_CONTROL_UNAVAILABLE",
            "RUNTIME_HISTORY_UNAVAILABLE",
            "RUNTIME_VERIFICATION_FAILED",
        ),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/main-model",
        operation_id="getMainModel",
        tag="Runtime Control",
        summary="활성 메인 모델 조회",
        description=(
            (
            "현재 메인 모델의 설정 상태와 실제 런타임 관측 결과를 조회합니다.\n"
            "\n"
            "- `active_profile`: 활성 프로필과 적용 중인 `gateway_policy`.\n"
            "- `gate`: 요청 수락 상태. `closed`이면 생성 요청은 `503 MAIN_MODEL_SWITCH_IN_PROGRESS`와 `Retry-After`를 반환합니다.\n"
            "- `runtime_state`: 설정 상태(`active` / `stopped`).\n"
            "- `last_operation`: 최근 전환 작업의 결과·단계·오류.\n"
            "- `observed_runtime`: 컨테이너·이미지·엔진 관측 결과. 설정과 다르면 상태 불일치입니다.\n"
            "\n"
            "`image_digest`는 레지스트리 다이제스트이며 로컬 `image_id`와 구분합니다. 확인할 수 없는 다이제스트·엔진 버전은 `null`입니다."
        )
        ),
        request_schema=None,
        response_schema="main_model_status_response.schema.json",
        error_codes=("MAIN_MODEL_CONTROL_UNAVAILABLE",),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/main-model/profiles",
        operation_id="listMainModelProfiles",
        tag="Runtime Control",
        summary="메인 모델 프로필 조회",
        description=(
            (
            "메인 모델 전환 후보와 각 후보의 지원 기능·검증 상태·사전 판단을 반환합니다. `active: true`가 현재 활성 프로필입니다.\n"
            "\n"
            "- `compatibility.status`: 기술적 호환성(`compatible` / `incompatible` / `unknown`).\n"
            "- `qualification.status`: 실제 장비 검증 여부(`verified` / `unverified`). 미검증 프로필에는 전환 시 `confirm_unverified: true`가 필요합니다.\n"
            "- `capabilities.deployed_input`: 전환 후 지원하는 입력 종류.\n"
            "- `upstream_model_id`, `revision`: 로딩할 모델과 고정 리비전.\n"
            "- `switch_preflight`: 정책 거부·GPU 예산 통과·런타임 정리 필요·예산 부족·관측 불가 등의 사전 판단. `fits`는 정책 예약 검사 통과이며 실제 모델 적재 성공을 보장하지 않습니다. 관측 실패는 `unknown`이며 런타임을 자동 중지하지 않습니다.\n"
            "\n"
            "반환된 프로필 ID로만 전환할 수 있습니다. 전환 후 공개 모델의 입력·요청 한도가 갱신됩니다."
        )
        ),
        request_schema=None,
        response_schema="main_model_profiles_response.schema.json",
        error_codes=("MAIN_MODEL_CONTROL_UNAVAILABLE",),
    ),
    EndpointSpec(
        method="POST",
        path="/admin/main-model/switch",
        operation_id="switchMainModel",
        tag="Runtime Control",
        summary="메인 모델 전환",
        description=(
            (
            "메인 모델 프로필 전환을 접수하고 `202`와 `operation_id`를 반환합니다. 전환 중 요청 수락을 차단하고 진행 중인 요청 완료를 기다린 뒤 런타임을 교체합니다.\n"
            "\n"
            "- `profile`: 프로필 목록에서 반환된 ID.\n"
            "- `confirm_unverified`: 미검증 프로필 전환에 필요한 확인 값. 호환되지 않는 프로필은 전환할 수 없습니다.\n"
            "- `request_id`: 선택적 멱등 키. 같은 키의 최근 작업을 재사용하면 `reused: true`입니다. 키는 일정 시간 후 만료됩니다.\n"
            "\n"
            "`GET /admin/main-model/operations/{operation_id}`로 완료 여부를 확인하세요. 검증에 실패하면 이전 프로필 복구를 시도합니다."
        )
        ),
        request_schema="main_model_switch_request.schema.json",
        response_schema=None,
        error_codes=(
            "NOT_FOUND",
            "CONFLICT",
            "GPU_BUDGET_EXCEEDED",
            "MAIN_MODEL_CONTROL_UNAVAILABLE",
        ),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/main-model/operations",
        operation_id="listMainModelOperations",
        tag="Runtime Control",
        summary="최근 메인 모델 전환 작업 목록 조회",
        description=(
            "최근 메인 모델 전환 작업을 최신 순서로 조회합니다. 보존 범위가 제한된 운영 이력이며 장기 감사 기록은 아닙니다. 각 항목은 작업 상세 조회와 같은 형식입니다."
        ),
        request_schema=None,
        response_schema="main_model_operation_list_response.schema.json",
        error_codes=("MAIN_MODEL_CONTROL_UNAVAILABLE",),
    ),
    EndpointSpec(
        method="GET",
        path="/admin/main-model/operations/{operation_id}",
        operation_id="getMainModelOperation",
        tag="Runtime Control",
        summary="메인 모델 전환 작업 조회",
        description=(
            (
            "전환 작업의 결과·진행 단계·실패 원인을 조회합니다.\n"
            "\n"
            "- `status`: 작업 상태·결과. `completed`, `failed`, `rollback_failed`는 종료 상태입니다.\n"
            "- `stage`: 진행 단계 또는 실패 지점. `status`와 다를 수 있습니다.\n"
            "- `error`: 전환 실패 원인.\n"
            "- `rollback_error`: 이전 프로필 복구 실패 원인. `rollback_failed`이면 수동 복구가 필요합니다.\n"
            "- `client_request_id`: 전환 요청의 멱등 키.\n"
            "\n"
            "종료 상태가 될 때까지 조회하세요. 가장 최근 작업은 `GET /admin/main-model`의 `last_operation`에서도 확인할 수 있습니다."
        )
        ),
        request_schema=None,
        response_schema="main_model_operation_response.schema.json",
        error_codes=("NOT_FOUND", "MAIN_MODEL_CONTROL_UNAVAILABLE"),
    ),
]

# ---------------------------------------------------------------------------
# Risk Signal Service 엔드포인트 (port 9605)
# ---------------------------------------------------------------------------

RISK_SIGNAL_SERVICE_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        method="GET",
        path="/health",
        operation_id="getRiskSignalServiceHealth",
        tag="Operations",
        summary="프로세스 상태 확인",
        description="프로세스가 살아 있는지만 확인합니다. 항상 HTTP 200을 반환하며 인증 없이 호출할 수 있습니다.",
        request_schema=None,
        response_schema=None,
    ),
    EndpointSpec(
        method="GET",
        path="/ready",
        operation_id="getRiskSignalServiceReadiness",
        tag="Operations",
        summary="서비스 준비 상태 확인",
        description=(
            "활성 탐지기의 필수 모델 의존 서비스가 준비되면 HTTP 200을 반환합니다. "
            "로컬 탐지기만 사용하는 구성에는 별도 모델 의존 서비스가 없습니다. "
            "필수 서비스가 준비되지 않으면 HTTP 503이며 `not_ready_dependencies`에서 원인을 확인할 수 있습니다."
        ),
        request_schema=None,
        response_schema="readiness_response.schema.json",
    ),
    EndpointSpec(
        method="GET",
        path="/metrics",
        operation_id="getRiskSignalServiceMetrics",
        tag="Monitoring",
        summary="Prometheus 지표 조회",
        description="Prometheus 형식의 Risk Signal Service 지표입니다. 탐지기별 시간 초과·파싱 실패·신호 건수를 반환하며 관리자 인증 설정을 따릅니다.",
        request_schema=None,
        response_schema=None,
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/prompt/assessments",
        operation_id="assessRiskPromptDetector",
        tag="Risk Signal",
        summary="프롬프트 공격 신호 탐지",
        description=(
            (
            "Prompt 탐지기(`risk-prompt`)로 프롬프트 인젝션·시스템 프롬프트 유출 신호를 탐지합니다. 지시 무시 유도·역할극 탈옥·문서 내 악성 지시·도구 악용을 다룹니다.\n"
            "\n"
            "최종 허용·차단은 호출 애플리케이션이 결정합니다. 탐지기가 비활성화된 배포에서는 `409 DETECTOR_DISABLED`입니다."
        )
        ),
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=("DETECTOR_DISABLED",),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/pii/assessments",
        operation_id="assessRiskPIIDetector",
        tag="Risk Signal",
        summary="개인정보 노출 신호 탐지",
        description=_PII_DETECTOR_DESCRIPTION,
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=("DETECTOR_DISABLED",),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/detectors/secret/assessments",
        operation_id="assessRiskSecretDetector",
        tag="Risk Signal",
        summary="시크릿 노출 신호 탐지",
        description=_SECRET_DETECTOR_DESCRIPTION,
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
        error_codes=("DETECTOR_DISABLED",),
    ),
    EndpointSpec(
        method="POST",
        path="/v1/risk/assessments",
        operation_id="assessRiskAggregate",
        tag="Risk Signal",
        summary="위험 신호 통합 탐지",
        description=(
            (
            "배포에서 활성화된 탐지기를 설정된 순서로 실행하고 결과를 통합합니다. 로컬 구성은 PII Protection·Secret Exposure를 실행하며 Prompt 런타임이 활성화된 구성에서 프롬프트 탐지를 추가합니다.\n"
            "\n"
            "하나라도 신호를 탐지하면 `risk_detected: true`입니다. HTTP 200이어도 `status=failed` 또는 `assessment_complete=false`이면 탐지가 완료되지 않은 결과이며 안전 판정으로 사용할 수 없습니다."
        )
        ),
        request_schema="risk_assessment_request.schema.json",
        response_schema="risk_assessment_response.schema.json",
    ),
]
