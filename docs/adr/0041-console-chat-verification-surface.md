# ADR-0041: Console은 공개 API를 그대로 쓰는 채팅 테스트 화면을 제공한다

## Status

Superseded by ADR-0047

## Context

메인 모델 전환, 설정 변경, runtime 재시작 뒤 운영자가 가장 먼저 확인하는 것은 "모델이
지금 실제로 답하는가"다. 지금까지 확인 수단은 두 가지였다.

- Scalar `/docs`: endpoint마다 JSON body를 직접 편집하는 범용 request builder다. SSE 응답을
  원문 그대로 보여 주고, 여러 턴 대화, 첫 토큰 시간, reasoning 분리를 다루지 않는다.
  `FASTAPI_DOCS_ENABLED=false`인 환경에서는 사용할 수 없다.
- `curl`: 응답 확인은 되지만 스트리밍 결과를 사람이 읽기 어렵고, request_id와 로그를
  잇는 일도 수동이다.

ADR-0027은 "Console이 Grafana와 Scalar를 다시 구현하지 않는다"고 정했다. 이 결정의 목적은
범용 API reference와 시계열 탐색기를 두 벌 유지하지 않는 것이다. 모델 응답을 확인하는
운영 작업은 그 두 도구가 맡지 않는 빈자리로 남아 있었다.

## Decision

### 1. 채팅 테스트는 공개 API의 한 client다

Console에 **채팅 테스트** 화면을 둔다. 이 화면은 다른 client와 같은 `GET /v1/models`와
`POST /v1/chat/completions`를 same-origin으로 호출한다.

- 새 backend endpoint, admin 전용 우회 경로, 서버 측 대화 저장을 만들지 않는다.
- Gateway의 validation, admission(메인 모델 gate, 동시성, circuit breaker), metrics, access log가
  다른 요청과 똑같이 적용된다. 화면에서 본 결과가 실제 client가 겪는 결과다.
- navigation 노출은 ADR-0040과 같이 `deployment.features`의 `chat` capability를 따른다.

### 2. 요청은 모델이 광고한 범위 안에서만 만든다

온도, 최대 출력 토큰, reasoning, 스트리밍, usage 포함 여부는 `/v1/models[].request_parameters`가
광고한 경우에만 화면에 나타나고 요청에 들어간다. 입력하지 않은 값은 보내지 않아 활성
profile의 기본값을 따른다. 광고된 범위를 벗어난 값은 보내기 전에 화면에서 거부한다.
Console은 profile별 한도를 복제해 두지 않는다.

대화 기록은 성공한 주고받기만 다음 요청에 포함한다. 실패한 턴을 보내면 user 메시지가
연속되고, 역할 교대를 요구하는 chat template이 요청을 거부하기 때문이다.

### 3. API 키는 관리자 키와 분리하고 메모리에만 둔다

공개 API가 `401`을 반환할 때만 API 키를 입력받는다. 관리자 키를 공개 API에 보내지 않는다.
API 키와 대화는 ADR-0027의 관리자 키와 같은 원칙으로 브라우저 탭 메모리에만 있고,
새로고침하거나 관리자 키를 지우면 함께 사라진다. localStorage/sessionStorage와 서버에
남기지 않는다.

### 4. 외부 의존성을 추가하지 않는다

SSE는 `fetch`, `ReadableStream`, `TextDecoder`로 직접 읽는다. OpenAI SDK, markdown renderer,
syntax highlighter를 추가하지 않는다. 모델 출력은 HTML로 해석하지 않고 plain text로 표시한다.
air-gap과 CSP(`connect-src 'self'`) 조건은 기존 Console과 같다.

### 5. 응답마다 진단 정보를 함께 보여 준다

각 응답에 request_id(Grafana가 있으면 요청 로그 링크), 첫 토큰 시간, 전체 시간, 입력·출력
토큰, 생성 속도를 표시한다. 스트림 중 오류는 Gateway가 보낸 오류 code와 message를 받은
부분 응답과 함께 보여 준다. 최대 토큰 도달로 잘린 응답, reasoning만 생성된 응답, 사용자가
중지한 응답은 이유를 문장으로 설명한다.

### 6. 범위를 좁게 유지한다

텍스트 여러 턴 대화, 시스템 프롬프트, 위 요청 설정, 중지까지만 제공한다. tool calling,
이미지·오디오 입력, structured output, Responses API, 대화 저장·내보내기, 프롬프트 모음은
만들지 않는다. 이 요청들은 계속 Scalar와 실제 client가 맡는다.

## Consequences

| Positive | Negative |
|---|---|
| 모델 전환 직후 Console을 떠나지 않고 실제 응답과 지연을 확인한다. | 채팅 테스트 요청도 GPU를 쓰고 공개 API metrics·로그·최근 트래픽 요약에 집계된다. |
| 공개 API와 같은 경로를 지나므로 admission 거부나 validation 오류도 그대로 재현된다. | Console이 유지할 UI 코드가 늘어난다. |
| request_id로 요청 로그까지 바로 이어진다. | 새 종류의 request parameter는 광고되더라도 화면을 고쳐야 나타난다. |
| npm dependency와 backend 변경이 없다. | markdown을 렌더링하지 않으므로 표·코드 블록은 원문 그대로 보인다. |

## Operational impact

채팅 테스트 요청은 일반 공개 API 요청이다. `/admin/traffic/recent`, Prometheus metrics, access
log에 그대로 나타나며 운영자 요청을 따로 표시하지 않는다. 사용자가 중지하면 연결을 닫으므로
Gateway에는 `client_disconnect` 스트림 종료로 기록된다.

## Migration notes

- ADR-0047이 이 화면의 current scope와 capability projection 규칙을 소유한다.
- 이 ADR의 공개 API client, 메모리 보관, same-origin, 진단 정보 원칙은 ADR-0047에 이어진다.

## Related

- [ADR-0027](0027-control-plane-runtime-configuration-and-console-boundary.md)
- [ADR-0040](0040-control-plane-korean-capability-ux.md)
- [ADR-0047](0047-control-plane-capability-aware-chat-playground.md)
- [API Reference](../reference/api_reference.md)
