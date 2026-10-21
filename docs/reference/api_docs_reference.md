# API 문서 화면

Gateway와 Risk Signal Service의 `/docs`는 Scalar API 문서 화면입니다.
API 연동 절차는 [API 연동 가이드](../guides/api-integration.md), 상세 계약은 [API 인터페이스](api_reference.md)를 참고하세요.

## 접속과 호출

| 서비스 | 문서 화면 | OpenAPI JSON | 인증이 활성화된 경우 |
|---|---|---|---|
| Gateway | `:9400/docs` | `:9400/openapi.json` | 사용자 API 키 또는 관리자 API 키 |
| Risk Signal Service | `:9405/docs` | `:9405/openapi.json` | 탐지 API: 내부 서비스 토큰, `/ready`·`/metrics`: 관리자 API 키 |

1. Gateway의 `Models`에서 공개 모델과 지원 기능을 확인합니다. 모델 목록에 있어도 런타임은 중지 상태일 수 있습니다.
2. 사용할 API에서 요청 예시를 선택합니다. `Chat`과 `Responses`는 기본 호출·스트리밍·도구 호출·구조화 출력 예시를 제공합니다.
3. 인증이 활성화돼 있으면 요청 창에서 해당 인증 항목을 선택합니다. 사용자 API 키와 관리자 API 키는 서로 대체할 수 없습니다.
4. **Test Request**로 호출하고 상태 코드·응답 본문을 확인합니다. 스트리밍은 오류 이벤트와 종료 이벤트까지 확인합니다.

cURL과 일반 HTTP 클라이언트 샘플은 선택한 요청 예시로 생성됩니다. 별도로 제공되는 OpenAI Python·JavaScript SDK 샘플은 기본 요청 예시를 사용합니다.
예시의 샘플링 값은 Gateway 기본값과 다를 수 있습니다. 지원 기능과 한도의 최신 값은 `GET /v1/models`, 운영자용 상세 정책은
`GET /admin/main-model`의 `active_profile.gateway_policy`에서 확인하세요.

## 화면과 용어

Gateway의 탐색 순서는 모델 조회 → 응답 생성 → 임베딩·검색·위험 탐지 → 런타임 관리 → 운영·지표입니다.

- API 제목·요청 예시·설명은 한국어를 기본으로 합니다.
- `Chat Completions`, `Responses`, `SSE`, `JSON Schema` 등 규격 이름과 경로·필드명·상태 값은 원래 표기를 유지합니다.
- `Runtime Control`의 GPU 정책 예약 비율과 실측 GPU 메모리 사용량은 구분합니다.
- 메인 모델 전환의 `status`는 작업 상태·결과, `stage`는 진행 단계 또는 실패 지점입니다.
- OpenAPI 자료형 목록은 플랫폼 모델 목록(`Models`)과 구분해 `Schemas`로 표시합니다.
- 긴 표와 코드 블록은 해당 영역 안에서 가로로 스크롤합니다.

문서에는 호출 방법·제약·결과 확인에 필요한 설명을 둡니다. 구현 과정·검토 메모·변경 이력과 장문의 운영 절차는 별도 문서에서 관리합니다.

## 문서 생성 위치

| 내용 | 소스 |
|---|---|
| API 제목·기본 설명·태그 | `src/ai_model_serving/api/endpoint_spec.py` |
| 첫 화면·태그 설명·설정별 한도 | `src/ai_model_serving/api_descriptions.py` |
| 요청·응답 스키마 | `specs/schemas/*.json` |
| 요청 예시 | `src/ai_model_serving/api_examples.py` |
| 기본 요청에서 생성하는 SDK 샘플 | `src/ai_model_serving/api_code_samples.py` |
| 상태별 오류 의미 | `configs/error_catalog.yaml` |
| OpenAPI 조합·오류 코드별 응답 | `src/ai_model_serving/openapi_contracts.py` |
| Scalar 설정·번들 버전·SRI 해시 | `src/ai_model_serving/docs_ui.py` |

`specs/openapi.gateway.yaml`과 `specs/openapi.risk-signal-service.yaml`은 생성 산출물입니다.
소스를 수정한 뒤 `make render-runtime-assets`로 갱신하고 `make validate`로 일치 여부를 확인합니다.
모델·한도는 `AppSettings`에서, 오류 상태·재시도 가능 여부는 실제 오류 정의에서 생성합니다.
화면 설명을 고치기 위해 요청·응답 계약을 별도로 복사하지 않습니다.

## 활성화와 네트워크

`FASTAPI_DOCS_ENABLED=false`이면 `/docs`와 `/openapi.json`이 비활성화됩니다.
문서 화면의 공개 여부와 API 호출 권한은 별개입니다. API 호출은 배포의 사용자·관리자·내부 서비스 인증 설정을 따릅니다.

Scalar JS는 애플리케이션에 포함된 번들을 같은 출처에서 제공합니다. 외부 CDN 없이 열리며 브라우저는 SRI 해시를 검증합니다.
Agent·MCP 연결·개발용 도구 모음·외부 Client 연결 버튼·텔레메트리·외부 폰트는 비활성화합니다.
API 인증 정보는 로컬 저장소에 영구 보관하지 않습니다(`persistAuth: false`).

번들 갱신 시 `docs_ui.py`의 버전·해시를 수정하고 `python scripts/build/fetch_docs_assets.py`로 다운로드합니다.
`make validate`는 네트워크 없이 로컬 번들의 해시를 검사합니다.
설정 항목은 [Scalar 공식 설정 문서](https://scalar.com/products/api-references/configuration)를 참고하세요.
