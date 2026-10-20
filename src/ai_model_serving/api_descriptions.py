from __future__ import annotations

from typing import Any

from .main_model.control import OPERATION_STAGES
from .settings_parts.types import AppSettings

# ---------------------------------------------------------------------------
# Gateway
#
# 문서 화면(Scalar `/docs`)에 보이는 모델 표·한도·파라미터 목록은 손으로 적지 않고
# 전부 AppSettings에서 만든다. 같은 값이 `/v1/models` 응답과 요청 검증에도 쓰이므로,
# configs를 고치면 문서·계약·검증이 한꺼번에 따라온다 -- 문서에만 숫자를 복사해 두면
# 프로필을 하나 바꿀 때 문서가 조용히 거짓말을 하게 된다.
# ---------------------------------------------------------------------------


def _codes(values: Any) -> str:
    """값 목록을 코드 표기로 나열한다. 비어 있으면 대시를 돌려준다."""
    items = [str(value) for value in values or ()]
    return ", ".join(f"`{item}`" for item in items) if items else "—"


def _bytes(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    if number < 1_048_576:
        return f"{number:,}바이트"
    return f"{number:,}바이트 ({number / 1_048_576:.1f} MiB)"


def _number(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _main_model_parameter(settings: AppSettings, name: str) -> dict[str, Any]:
    """공개 목록에서 메인 모델의 파라미터 정의 하나를 꺼낸다(없으면 빈 dict)."""
    main_model_id = settings.runtime("main_llm").model
    for model in settings.public_models:
        if model.get("id") == main_model_id:
            definition = (model.get("request_parameters") or {}).get(name)
            return definition if isinstance(definition, dict) else {}
    return {}


def models_tag_summary(settings: AppSettings) -> str:
    """Models 그룹의 표지.

    태그 섹션은 Scalar에서 최소 높이를 갖는다. 한 줄만 두면 아래가 통째로 비어
    빈 상자처럼 보이므로, 그 그룹을 훑는 데 필요한 만큼(모델 목록)은 여기 둔다.
    파라미터·프로필 같은 세부는 GET /v1/models 오퍼레이션이 가져간다.
    """
    lines = [
        "Gateway가 호출자에게 공개하는 모델 목록입니다. 아래 표는 이 배포 설정에서 "
        "자동으로 만들어지며, 지금 실제로 적용 중인 값은 `GET /v1/models` 응답에서 확인하세요.",
        "",
        # 3열까지 줄인다. 열이 많으면 좁은 본문 폭에서 `chat.completions.vision` 같은
        # 무공백 식별자가 글자 단위로 쪼개진다(chat.comple/tions.visi/on).
        # backend(내부 compose service 이름)와 파라미터 개수 안내는 표에서 뺐다.
        "| 모델 | 입력 | 기능 |",
        "|---|---|---|",
    ]
    fixed_notes: list[str] = []
    for model in settings.public_models:
        lines.append(
            "| `{id}` | {modalities} | {capabilities} |".format(
                id=model.get("id", "—"),
                modalities=_codes(model.get("input_modalities")),
                capabilities=_codes(model.get("capabilities")),
            )
        )
        fixed = model.get("fixed_parameters") or {}
        if fixed:
            values = ", ".join(f"`{key}={value}`" for key, value in fixed.items())
            fixed_notes.append(
                f"- `{model.get('id', '—')}`는 조정 가능한 파라미터가 없습니다. {values}으로 고정입니다."
            )
    if fixed_notes:
        lines.append("")
        lines += fixed_notes
    return "\n".join(lines)


def models_operation_detail(settings: AppSettings) -> str:
    """공개 모델 조회에서 확인할 필드와 활성 프로필의 관계를 설명한다."""
    return (
        "`display_name`·`upstream_model_id`·`backend`는 메인 모델의 신원과 실행 엔진, `context_window`는 문맥 토큰 한도입니다. "
        "`request_parameters`는 모델별 허용 파라미터와 범위(`min`, `max`, `max_items`, `allowed`)를, "
        "`request_limits`는 입력 종류별 개수·크기 한도를 반환합니다. 요청 예시의 값은 Gateway 기본값과 다를 수 있습니다.\n\n"
        "`local-main`은 활성 메인 모델 프로필의 공개 이름입니다. 프로필 전환 후 입력 종류·토큰 한도·허용 파라미터가 "
        "달라질 수 있으므로 응답의 최신 값을 사용하세요. 모델 목록에 포함돼 있어도 런타임은 중지 상태일 수 있습니다. "
        "운영자는 `GET /admin/main-model/profiles`에서 전환 후보와 검증 상태를 확인할 수 있습니다."
    )


def chat_tag_summary(settings: AppSettings) -> str:
    """Chat Completions의 용도와 현재 기능 조회 경로를 설명한다."""
    return (
        "메시지 목록으로 모델 응답을 생성하는 OpenAI 호환 Chat Completions API입니다. "
        "스트리밍·도구 호출·구조화 출력·멀티모달 입력의 지원 범위는 활성 프로필에 따라 다릅니다. "
        "현재 기능과 한도는 `GET /v1/models`에서 확인하세요."
    )


def chat_operation_detail(settings: AppSettings) -> str:
    """기본 프로필에서 생성한 요청 한도와 응답 처리 방법을 설명한다."""
    policy = settings.default_main_model_gateway_policy or {}
    limits = policy.get("request_limits") or {}
    parameters = policy.get("request_parameter_policy") or {}
    if not policy:
        return "현재 지원 기능과 요청 한도는 `GET /v1/models`에서 확인하세요."
    lines = [
        "아래 한도는 **기본 프로필** 기준입니다. 활성 프로필의 최신 값은 `GET /v1/models`의 "
        "`request_parameters`와 `request_limits`에서 확인하세요.",
        "", "### 요청 파라미터", "",
        f"- 허용 파라미터: {_codes(parameters.get('supported_parameters'))}",
        "- `max_tokens`와 `max_completion_tokens`는 출력 토큰 한도를 지정합니다. 둘 중 하나만 사용하세요.",
        "- 메시지 역할: `system`, `developer`, `user`, `assistant`, 도구 호출 시 `tool`. "
        "이 플랫폼은 `developer`를 `system`과 동일하게 처리합니다.",
    ]
    if parameters.get("allow_unlisted_parameters") is False:
        lines.append("- 미지원 파라미터는 `422 VALIDATION_ERROR`입니다. `error.param`에서 필드명을 확인하세요.")
    dropped = parameters.get("drop_upstream_parameters") or []
    if dropped:
        lines.append(f"- {_codes(dropped)}: Gateway에서만 처리하며 모델 런타임에 전달하지 않습니다.")
    lines += [
        "", "### 입력·출력 한도", "",
        f"- 컨텍스트 상한: 입력과 출력 합계 {_number(limits.get('max_model_len'))}토큰.",
        "- 요청별 출력 한도와 `n` 범위는 아래 요청 스키마를 따릅니다. "
        "정확한 입력 토큰 수는 런타임이 토크나이저·대화 템플릿·미디어 전처리를 적용해 계산합니다.",
        "- `max_tokens`를 생략하면 활성 런타임의 기본 출력 예산을 사용합니다. "
        "입력과 출력 예산 합이 컨텍스트 상한을 넘으면 `422 VALIDATION_ERROR`입니다.",
        f"- 요청 본문 상한: {_bytes(settings.max_request_body_bytes)}(base64 미디어 포함). "
        "초과하면 `413 REQUEST_TOO_LARGE`입니다.",
        "", "### 스트리밍과 응답 종료", "",
        "- `stream: true`로 SSE 응답을 받습니다. `stream_options.include_usage: true`로 마지막 청크에 토큰 사용량을 포함합니다.",
        f"- 스트림 상한: {_number(settings.streaming_max_duration_seconds)}초, "
        f"{_number(settings.streaming_max_chunks)}청크, {_bytes(settings.streaming_max_bytes)}.",
        "- HTTP 200 이후에도 SSE `error` 이벤트가 올 수 있습니다. 오류 이벤트·`finish_reason`·최종 `data: [DONE]`을 "
        "함께 확인하세요. `[DONE]` 누락은 정상 종료로 간주하지 마세요.",
        "- `finish_reason: length`는 출력 한도에 도달한 응답입니다. 추론이 출력 예산을 모두 사용하면 "
        "`content: null`과 비어 있지 않은 `reasoning`이 반환될 수 있습니다.",
    ]
    tool = parameters.get("tool_calling") or {}
    if tool:
        choice = _main_model_parameter(settings, "tool_choice")
        lines += [
            "", "### 도구 호출", "",
            f"- 지원: `{str(tool.get('enabled', False)).lower()}`. "
            f"`tool_choice` 허용값: {_codes(choice.get('allowed'))}.",
            f"- 지정 함수 선택 지원: `{str(choice.get('allow_named', False)).lower()}`.",
            f"- 병렬 호출 지원: `{str(tool.get('allow_parallel_tool_calls', False)).lower()}`. "
            "미지원 프로필에서는 `parallel_tool_calls: true`를 사용할 수 없습니다.",
        ]
    response_format = parameters.get("response_format") or {}
    if response_format:
        schema = response_format.get("json_schema") or {}
        lines += [
            "", "### 구조화 출력", "",
            f"- `response_format.type` 허용값: {_codes(response_format.get('types'))}.",
            "- `json_object`: 메시지에 JSON 출력을 지시해야 합니다. 특정 스키마와의 일치는 보장하지 않습니다.",
        ]
        if schema:
            lines += [
                "- `json_schema`: 루트 `object`, `additionalProperties: false`를 사용하세요. "
                "선택 필드는 nullable union(`[\"type\", \"null\"]`)으로 표현하며 외부 `$ref`는 지원하지 않습니다.",
                f"- 스키마 상한: {_bytes(schema.get('max_schema_bytes'))}, 깊이 {_number(schema.get('max_depth'))}, "
                f"전체 속성 {_number(schema.get('max_total_properties'))}개.",
                "- 생성 결과가 스키마를 만족하지 못하면 `STRUCTURED_OUTPUT_INVALID`입니다. "
                "스키마와 출력 토큰 한도를 확인하세요. 숫자의 `minimum`·`maximum`, 문자열의 `maxLength`·`pattern`은 "
                "반복 출력을 줄이는 데 도움이 되지만 정상 종료를 보장하지는 않습니다.",
            ]
    reasoning = parameters.get("reasoning") or {}
    if reasoning:
        lines += [
            "", "### 추론", "",
            f"- `reasoning` 지원: `{str(reasoning.get('enabled', False)).lower()}`, "
            f"기본값: `{str(reasoning.get('default', False)).lower()}`.",
            "- `reasoning: true`로 활성화합니다. 추론 토큰도 출력 한도에 포함되므로 `max_tokens`를 함께 조정하세요.",
        ]
    lines += [
        "", "### 토큰 확률과 재현성", "",
        "- `logprobs`와 `top_logprobs`: 토큰 확률을 반환합니다. `top_logprobs`에는 `logprobs: true`가 필요합니다.",
        "- `logit_bias`: 활성 프로필의 토크나이저에 따른 토큰 ID를 사용합니다. 프로필 전환 후 ID가 달라질 수 있습니다.",
        "- `seed`: 재현성을 높이는 값이며 동일한 결과를 보장하지 않습니다.",
    ]
    if limits.get("input_modalities"):
        lines += [
            "", "### 멀티모달 입력", "",
            f"지원 입력: {_codes(limits.get('input_modalities'))}. 미지원 입력·형식·크기는 "
            "`422 VALIDATION_ERROR`이며 `error.param`에서 원인 필드를 확인할 수 있습니다.",
            "", "| 항목 | 이미지 | 오디오 | 비디오 |", "|---|---|---|---|",
            "| 최대 개수 | {} | {} | {} |".format(*(_number(limits.get(f"max_{kind}_inputs")) for kind in ("image", "audio", "video"))),
            "| 최대 크기 | {} | {} | {} |".format(*(_bytes(limits.get(f"max_{kind}_bytes")) for kind in ("image", "audio", "video"))),
            "", f"- 이미지 URL 형식: {_codes(limits.get('allowed_image_url_schemes'))}. "
            f"MIME 유형: {_codes(limits.get('allowed_image_mime_types'))}.",
            f"- 오디오: 인라인 base64. 형식: {_codes(limits.get('allowed_audio_formats'))}.",
            f"- 비디오 URL 형식: {_codes(limits.get('allowed_video_url_schemes'))}. "
            f"MIME 유형: {_codes(limits.get('allowed_video_mime_types'))}.",
            f"- 이미지 해상도 상한: {_number(limits.get('max_image_pixels'))}픽셀. 해상도를 확인할 수 없는 이미지는 거부합니다.",
        ]
        if limits.get("max_video_frames") or limits.get("max_video_duration_seconds"):
            lines.append(f"- 비디오 상한: {_number(limits.get('max_video_frames'))}프레임, "
                         f"{_number(limits.get('max_video_duration_seconds'))}초, 프레임당 {_number(limits.get('max_video_frame_pixels'))}픽셀.")
    return "\n".join(lines)



def responses_tag_summary(settings: AppSettings) -> str:
    """Responses API의 용도와 대화 상태 관리 방법을 설명한다."""
    return (
        "항목 기반 입력·출력과 이벤트 유형별 스트리밍을 제공하는 OpenAI 호환 Responses API입니다. "
        "Chat Completions와 같은 활성 메인 모델을 사용합니다. "
        "대화를 이어가려면 이전 응답과 도구 실행 결과를 다음 요청의 `input`에 포함하세요. 서버는 응답을 저장하지 않습니다."
    )

def embeddings_tag_summary(settings: AppSettings) -> str:
    """Embeddings 그룹의 표지. 쓸 수 있는 모델과 차원까지만."""
    lines = [
        "OpenAI 호환 embedding API입니다. 모델마다 출력 차원이 고정되어 있고, "
        "Gateway가 요청 차원과 응답 차원이 일치하는지 확인합니다.",
    ]
    profiles = settings.embedding_profiles or {}
    if profiles:
        lines.append("")
        for name, profile in profiles.items():
            lines.append(
                f"- `{name}` — 기본 {_number(getattr(profile, 'default_dimensions', None))}차원"
            )
        lines += ["", "요청 파라미터와 한도는 아래 `POST /v1/embeddings` 설명에 있습니다."]
    return "\n".join(lines)


def embeddings_operation_detail(settings: AppSettings) -> str:
    lines = [
        "텍스트 embedding API입니다. 모델마다 출력 차원이 고정되어 있고, Gateway가 요청 차원과 "
        "응답 차원이 일치하는지 확인합니다.",
    ]
    if settings.embedding_profiles:
        lines += [
            "",
            "| 모델 | 기본 차원 | 허용 차원 | encoding_format |",
            "|---|---|---|---|",
        ]
        for model_id, profile in settings.embedding_profiles.items():
            policy = profile.request_parameter_policy or {}
            lines.append(
                "| `{model}` | {default} | {dims} | {formats} |".format(
                    model=model_id,
                    default=f"`{profile.default_dimensions}`",
                    dims=_codes(policy.get("dimensions")),
                    formats=_codes(policy.get("encoding_formats", ["float"])),
                )
            )
        lines += [
            "",
            "- `base64`는 little-endian float32 배열을 인코딩한 문자열로 반환됩니다. openai-python은 "
            "numpy가 설치되어 있으면 이 형식을 기본으로 요청하므로, 형식을 지정하지 않은 공식 SDK 호출도 "
            "그대로 동작합니다.",
            "- `input`은 문자열 또는 비어 있지 않은 문자열 배열입니다. 토큰 id 배열은 받지 않습니다.",
        ]
    return "\n".join(lines)


def _runtime_control_tag_description(settings: AppSettings) -> str:
    """런타임 제어의 순서·GPU 정책 예산·전환 단계를 설명한다."""
    meanings = {
        "pending": "작업 접수", "preparing": "이미지·가중치 준비",
        "draining": "요청 수락을 차단하고 진행 중인 요청 완료 대기",
        "stopping": "이전 런타임 중지", "starting": "새 런타임 시작",
        "validating": "추론 요청으로 런타임 검증", "rolling_back": "이전 프로필 복구",
        "completed": "전환 완료", "failed": "전환 실패", "rollback_failed": "복구 실패, 수동 조치 필요",
    }
    lines = [
        "메인 모델과 보조 런타임의 상태·프로필을 관리합니다. 관리자 인증이 활성화된 배포에서는 관리자 API 키를 사용하세요.",
        "", "### 시작·중지", "",
        "1. `GET /admin/runtimes`에서 상태를 조회합니다.",
        "2. `POST /admin/runtimes/{service_key}/plans`로 변경 영향을 확인합니다.",
        "3. 같은 변경 내용과 반환된 `plan_digest`로 `PATCH /admin/runtimes/{service_key}`를 호출합니다. 메인 모델의 키는 `main`입니다.",
        "", "`vram_fraction`과 `budget`은 동시 실행 판단에 사용하는 **GPU 정책 예약 비율**입니다. "
        "실측 GPU 메모리 사용량이 아닙니다. `force: true`는 계획에 포함된 낮은 우선순위 보조 런타임의 자동 중지를 허용합니다.",
        "", "### 메인 모델 전환", "",
        "`POST /admin/main-model/switch`는 `202`와 `operation_id`를 반환합니다. "
        "`GET /admin/main-model/operations/{operation_id}`로 결과를 확인하세요. "
        "전환·중지 중 요청 수락이 차단되면 Chat Completions와 Responses는 "
        "`503 MAIN_MODEL_SWITCH_IN_PROGRESS`와 `Retry-After`를 반환합니다.",
        "", "| 단계 (`stage`) | 의미 |", "|---|---|",
    ]
    lines.extend(f"| `{stage}` | {meanings.get(stage, '')} |" for stage in OPERATION_STAGES)
    lines += [
        "", "`status`는 작업 상태·결과이며 `stage`는 진행 단계 또는 실패 지점입니다. "
        "예를 들어 검증 실패 후 복구에 성공해도 `status=failed`, `stage=validating`이 남을 수 있습니다. "
        "`status=rollback_failed`이면 수동 복구가 필요합니다.",
    ]
    if settings.deployment_target.adaptive:
        lines += ["", "이 배포는 자동 CPU/GPU 선택을 사용하므로 수동 Profile 전환은 잠겨 있습니다. Main 시작·중지로 자동 선택을 재개·중단하세요."]
    elif any(p[0] == "cpu-gguf-text" for p in settings.main_model_profile_summaries):
        lines += ["", "CPU 모델도 같은 전환 API에서 선택합니다. CPU 준비는 RAM·Artifact·고정 image를 검사하며 GPU 예약을 요구하지 않습니다. 준비 실패는 기존 엔진을 유지하고, 교체 단계의 실패는 이전 엔진을 재검증하여 복구합니다. 전환 후 실제 모델·기능·한도를 다시 조회하세요."]
    return "\n".join(lines)


def gateway_tags_metadata(settings: AppSettings) -> list[dict[str, str]]:
    """Gateway OpenAPI 태그 설명을 만든다. 모델·한도 값은 settings에서 나온다."""
    return [
        {
            "name": "Models",
            "description": models_tag_summary(settings),
        },
        {
            "name": "Chat",
            "description": chat_tag_summary(settings),
        },
        {
            "name": "Responses",
            "description": responses_tag_summary(settings),
        },
        {
            "name": "Embeddings",
            "description": embeddings_tag_summary(settings),
        },
        {
            "name": "Retrieval",
            "description": "텍스트 임베딩의 코사인 유사도로 문서 관련도를 평가합니다. 기본 모델은 `local-embed-ko`이며 `local-embed`도 선택할 수 있습니다.",
        },
        {
            "name": "Risk",
            "description": (
                "개인정보·시크릿 노출과 프롬프트 공격의 탐지 신호를 반환합니다. "
                "최종 허용·차단은 호출 애플리케이션이 결정합니다.\n\n"
                "- PII Protection: 개인정보 탐지(D1, D2, D5).\n"
                "- Secret Exposure: 시크릿·자격증명 탐지(D4, D5).\n"
                "- Prompt: 프롬프트 인젝션·시스템 프롬프트 유출 탐지(A1, A2).\n\n"
                "HTTP 200이어도 `status=failed` 또는 `assessment_complete=false`이면 탐지가 완료되지 않은 결과입니다. "
                "이때 `risk_detected=false`를 안전 판정으로 사용하지 마세요."
            ),
        },
        {
            "name": "Runtime Control",
            "description": _runtime_control_tag_description(settings),
        },
        {
            "name": "Operations",
            "description": _OPERATIONS_TAG,
        },
        {
            "name": "Monitoring",
            "description": "Prometheus 형식의 Gateway 지표를 조회합니다. 관리자 인증 설정을 따릅니다.",
        },
    ]


_OPERATIONS_TAG = """`/health`는 프로세스 상태, `/ready`는 배포에서 필수로 사용하는 런타임과 Risk Signal Service의 준비 상태를 확인합니다.

### 요청 추적과 오류 처리

| 항목 | 용도 |
|---|---|
| `X-Request-Id` | 요청 추적 ID. 서버 접근 로그의 `request_id`와 같습니다 |
| `X-Error-Code` / `error.code` | 같은 HTTP 상태에서도 구분되는 오류 원인 |
| `error.param` | 수정할 요청 필드 |
| `error.retryable` | 오류의 재시도 가능 여부 |
| `Retry-After` | 재시도 전 대기 시간(초) |

각 API의 오류 응답에서 코드별 의미를 확인하세요. 재시도 전에는 같은 작업을 다시 실행해도 되는지 확인해야 합니다.

- `422`: `error.param`과 모델의 `request_parameters`·`request_limits`를 확인하세요.
- `503`: `error.code`와 `/ready`의 의존 서비스 상태를 확인하세요. 모델 전환 중이면 완료를 기다리세요.
- 스트리밍: HTTP 200만으로 성공을 판단하지 말고 SSE 오류 이벤트와 최종 종료 이벤트를 확인하세요.
"""


def _auth_section(settings: AppSettings) -> str:
    """실제 공개·관리자 인증 설정에 맞는 호출 방법을 안내한다."""
    security = settings.security
    lines = ["## 인증", ""]
    if not security.api_key_required and not security.admin_api_key_required:
        lines.append("이 배포의 사용자·관리자 API는 인증이 비활성화돼 있습니다. `Authorization` 헤더 없이 호출할 수 있습니다.")
        return "\n".join(lines)
    if security.api_key_required:
        lines.append("- 사용자 API(`/v1/*`): `Authorization: Bearer <API_KEY>` (`bearerAuth`).")
    else:
        lines.append("- 사용자 API(`/v1/*`): 인증 없이 호출할 수 있습니다.")
    if security.admin_api_key_required:
        lines.append("- 관리자 API(`/ready`, `/metrics`, 인증이 필요한 `/admin/*`): "
                     "`Authorization: Bearer <ADMIN_API_KEY>` (`adminBearerAuth`).")
    else:
        lines.append("- 관리자 API: 인증 없이 호출할 수 있습니다.")
    lines += ["", "사용자 API 키와 관리자 API 키는 서로 대체할 수 없습니다. 요청 창에서 해당 인증 항목을 선택하세요."]
    return "\n".join(lines)


def _main_runtime_description(settings: AppSettings) -> str:
    """설정된 실행 모드와 선택 후보를 설명하며 현재 활성 상태와 구분한다."""
    target = settings.deployment_target
    if not target.supports("chat"):
        return ""
    lines = ["## 메인 모델 실행", ""]
    if target.adaptive:
        lines.append("CPU/GPU 자동 선택 모드입니다. 아래 모델은 자동 전환 후보이며 수동 Profile 전환은 잠겨 있습니다. 현재 엔진·선택 이유·요청 상태는 `GET /admin/main-model`에서 확인하세요.")
    elif target.supports("model_switching"):
        lines.append("수동 모델 선택 모드입니다. GPU 모델과 CPU 모델을 `POST /admin/main-model/switch`로 선택할 수 있습니다. CPU 자동 복구는 활성화되지 않으며, 선택한 모델은 재시작 뒤에도 유지됩니다.")
    elif target.control_mode == "managed_cpu":
        lines.append("플랫폼 관리형 CPU 모드입니다. 고정 GGUF 모델을 llama.cpp로 실행합니다. 현재 준비 상태는 `/ready`에서 확인하세요.")
    elif target.runtime_backend == "llama-cpp":
        lines.append("외부 CPU Runtime 모드입니다. 실제 GGUF 모델은 서버 운영자가 지정합니다. 플랫폼의 관리형 Qwen 모델이 실행 중이라고 가정하지 마세요.")
    else:
        lines.append("외부 메인 Runtime 모드입니다. 모델 실행·변경은 서버 운영자가 관리합니다.")
    candidates = list(zip(settings.main_model_profile_summaries, settings.main_model_profile_policies))
    if candidates:
        lines += ["", "| 모델 후보 | 실행 방식 | 입력 | 문맥 / 최대 출력 토큰 |", "|---|---|---|---|"]
        for (profile_id, name, _), policy in candidates:
            limits = policy.get("request_limits", {})
            engine = "CPU · llama.cpp" if profile_id == "cpu-gguf-text" else "Apple Silicon · MLX" if target.runtime_backend == "mlx" else "GPU · vLLM"
            lines.append(f"| {name} | {engine} | {_codes(limits.get('input_modalities'))} | {_number(limits.get('max_model_len'))} / {_number(policy.get('max_output_tokens'))} |")
    elif target.control_mode == "managed_cpu":
        for model in settings.public_models:
            if model['id'] == settings.runtime('main_llm').model:
                policy = settings.default_main_model_gateway_policy
                lines += ["", f"모델: **{model.get('display_name', model['id'])}** · `{model.get('upstream_model_id', '')}`", "", f"텍스트 입력 · 문맥 {_number(policy.get('request_limits', {}).get('max_model_len'))} / 최대 출력 {_number(policy.get('max_output_tokens'))} tokens · Chat / Responses / SSE"]
    lines += ["", "공개 이름은 `local-main`을 유지합니다. 실제 모델·입력·한도는 전환 후 `GET /v1/models`의 `display_name`, `upstream_model_id`, `backend`, `context_window`, `request_parameters`를 다시 확인하세요."]
    return "\n".join(lines)


def gateway_description(settings: AppSettings) -> str:
    """API 첫 호출과 배포별 인증 안내를 제공한다."""
    if not settings.feature_enabled("chat"):
        return (
            "모델 런타임 없이 Control Plane과 개인정보·시크릿 위험 탐지를 제공하는 Core 배포입니다.\n\n"
            "`GET /v1/models`는 빈 목록을 반환합니다. Chat Completions·Responses는 "
            "`503 MODEL_UNAVAILABLE`이며 모델 런타임의 중지가 Core 서비스의 장애를 뜻하지는 않습니다.\n\n"
            + _auth_section(settings)
        )
    auth = '  -H "Authorization: Bearer $API_KEY" \\\n' if settings.security.api_key_required else ''
    features = ["모델 응답 생성"]
    if settings.feature_enabled("embeddings"):
        features.append("텍스트 임베딩")
    if settings.feature_enabled("retrieval"):
        features.append("문서 관련도 평가")
    if settings.feature_enabled("risk"):
        features.append("위험 신호 탐지")
    return f"""{'·'.join(features)}를 제공하는 Gateway API입니다.
현재 모델별 지원 기능과 요청 한도는 `GET /v1/models`에서 확인하세요.

{_main_runtime_description(settings)}

## 첫 호출

아래 로컬 주소를 실제 Gateway 주소로 바꾸세요. 사용자 인증이 활성화돼 있으면 `API_KEY`도 설정해야 합니다.

```bash
GATEWAY_URL='http://127.0.0.1:9400'
curl --fail-with-body "$GATEWAY_URL/v1/chat/completions" \\\n{auth}  -H "Content-Type: application/json" \\\n  -d '{{
    "model": "{settings.runtime('main_llm').model}",
    "messages": [
      {{"role": "user", "content": "안녕하세요"}}
    ]
  }}'
```

응답의 `choices[0].message.content`, `finish_reason`, `usage`를 확인하세요.
요청 예시와 코드 샘플은 각 API의 요청 영역에서 선택할 수 있습니다.

{_auth_section(settings)}
"""


# ---------------------------------------------------------------------------
# Risk Signal Service
# ---------------------------------------------------------------------------

RISK_SIGNAL_SERVICE_TAGS_METADATA = [
    {"name": "Operations", "description": "프로세스 상태와 활성 탐지기의 의존 서비스 준비 상태를 확인합니다."},
    {"name": "Monitoring", "description": "Prometheus 형식의 서비스·탐지기 지표를 조회합니다. 관리자 인증 설정을 따릅니다."},
    {"name": "Risk Signal", "description": "개인정보·시크릿 노출과 프롬프트 공격의 탐지 신호를 조회합니다. "
     "HTTP 200이어도 `status=failed` 또는 `assessment_complete=false`이면 탐지가 완료되지 않은 결과입니다. "
     "이때 `risk_detected=false`를 안전 판정으로 사용하지 마세요."},
]

RISK_SIGNAL_SERVICE_DESCRIPTION_TEMPLATE = """Gateway와 내부 서비스에서 사용하는 위험 신호 탐지 API입니다.
내부 서비스 인증이 활성화돼 있으면 `Authorization: Bearer <INTERNAL_SERVICE_TOKEN>`을 사용하세요.
탐지 API의 내부 서비스 토큰과 운영 API의 관리자 API 키는 구분됩니다.
`/ready`와 `/metrics`는 관리자 인증이 활성화돼 있으면 `Authorization: Bearer <ADMIN_API_KEY>`가 필요합니다.

## 탐지기

| 탐지기 | 실행 방식 | 탐지 대상 | 코드 |
|---|---|---|---|
| PII Protection | 로컬 정규식 | 개인정보 | D1, D2, D5 |
| Secret Exposure | 로컬 정규식·엔트로피 | 시크릿·자격증명 | D4, D5 |
| Prompt | 모델 런타임 (`risk-prompt`) | 프롬프트 인젝션·시스템 프롬프트 유출 | A1, A2 |

통합 탐지는 배포에서 활성화된 탐지기를 설정된 순서로 실행합니다. 로컬 탐지기만 사용하는 구성은 PII Protection과
Secret Exposure를 실행하며, Prompt 런타임이 활성화된 구성에서 프롬프트 탐지를 추가합니다.

## 결과 확인

- 하나라도 위험 신호를 탐지하면 `risk_detected: true`입니다.
- `status`와 `assessment_complete`를 함께 확인하세요. 탐지 실패는 안전 판정이 아닙니다.
- 최종 허용·차단은 호출 애플리케이션이 결정합니다. 이 API는 `allow`, `block`, `decision`, `action`을 반환하지 않습니다.
- 원문 개인정보·시크릿은 탐지 응답·로그·지표에 포함하지 않습니다.

`/ready`는 필수 모델 의존 서비스가 준비되면 HTTP 200, 준비되지 않았으면 HTTP 503을 반환합니다.
로컬 탐지기만 사용하는 구성에는 별도 모델 의존 서비스가 없습니다.
"""
