# ADR-0047: Control Plane Chat은 capability-aware model playground로 확장한다

## Status

Accepted

## Context

ADR-0041의 채팅 테스트는 공개 `/v1/models`와 `/v1/chat/completions`를 그대로 사용해
모델 전환 뒤 실제 응답을 확인하는 최소 verification surface로 시작했다. 당시에는 text,
temperature, max_tokens, reasoning, streaming만 다루고 tool calling, multimodal,
structured output은 Scalar와 실제 client에 남겼다.

이후 플랫폼의 모델 계약이 확장됐다.

- Linux Gemma profile은 tools, reasoning, structured output, logprobs와 image/audio/video를
  profile별로 광고한다.
- Qwen profile은 같은 `local-main` alias를 쓰면서도 tool/reasoning을 광고하지 않는다.
- macOS Metal profile은 tools/reasoning을 지원하지만 현재 MTP 조합에서는 structured output을
  광고하지 않는다.
- `GET /v1/models`는 `backend`, `capabilities`, `input_modalities`,
  `request_limits`, `request_parameters`를 현재 active profile에 맞게 투영한다.
- vLLM 0.30.0 qualification으로 Linux engine candidate의 tools/reasoning/structured/multimodal
  경로를 다시 확인했다.

현재 Console은 이 계약 중 일부만 읽기 때문에 server capability와 UI 사이에 표현 격차가 있다.
이 격차를 profile 이름이나 backend 이름을 frontend에 복제해서 메우면 두 번째 configuration
authority가 생긴다.

## Decision

### 1. public request UI의 authority는 `GET /v1/models`다

Chat UI는 public model listing에서 다음 값을 읽는다.

- `id`
- `backend`
- `capabilities`
- `input_modalities`
- `request_limits`
- `request_parameters`

Frontend는 profile id, OS, target 이름, backend 이름으로 capability를 추론하지 않는다.
광고되지 않은 기능은 숨기고 요청에도 넣지 않는다. browser-side validation은 빠른 UX
feedback일 뿐 최종 request authority는 계속 Gateway다.

Admin Main Model 상태가 필요한 정보는 public capability와 합치지 않는다. active profile id,
runtime artifact 같은 operator evidence를 보여 줄 필요가 생기면 기존 Admin API에서 별도로
읽어 secondary diagnostic context로 표시한다.

### 2. parameter UI는 contract normalization 뒤 렌더링한다

`request_parameters`의 raw dictionary를 React component가 직접 해석하지 않는다.
Frontend에 pure normalization layer를 두어 다음 constraint 의미를 보존한다.

- `min` / `min_exclusive`
- `max` / `max_exclusive`
- `enum` / `allowed`
- `const`
- `requires`
- `aliases`
- `min_items` / `max_items`
- nested `properties`

단순 scalar parameter는 schema-driven control로 투영한다. tools, response_format,
logit_bias, multimodal content처럼 작업 의미가 큰 object/array surface는 dedicated control을
사용한다. 모든 값을 generic JSON editor 하나로 대체하지 않는다.

### 3. 기본 UI와 고급 UI의 정보 밀도를 나눈다

Composer와 Basic 설정은 모델 사용 의도를 먼저 보여 준다.

- model/backend identity
- input modality/capability summary
- reasoning
- max output tokens
- streaming

Sampling/penalty/diagnostic parameter는 Advanced에 둔다. 이 구분은 parameter를 숨기는 것이
아니라 사용 빈도와 의미에 따라 기본 정보 밀도를 줄이는 presentation 결정이다.

Server가 boolean reasoning만 광고하면 boolean만 제공한다. 다른 provider가 effort level을
사용한다는 이유로 Console이 임의의 Low/Medium/High 의미를 만들지 않는다.

### 4. multimodal input은 public content contract를 그대로 만든다

별도 upload backend를 추가하지 않는다. Browser는 지원 modality와 `request_limits`를 보고
Chat content part를 만든다.

- image: data URL
- audio: base64 data + format
- video: data URL

파일 개수, byte size, MIME/format, browser가 신뢰성 있게 알 수 있는 image dimension은
선제 검사할 수 있다. frame count, codec decode와 같은 복잡한 검증을 frontend가 재구현하지
않고 Gateway 오류를 그대로 보여 준다.

### 5. tool calling은 simulator로 제공한다

Console은 arbitrary function executor, MCP client, plugin runtime을 소유하지 않는다.

Assistant가 `tool_calls`를 반환하면 이름과 arguments를 표시하고 operator가 tool result를
직접 입력해 `role=tool` message로 이어서 보낼 수 있다. 이 방식으로 parser와
assistant → tool → assistant round trip은 검증하지만 임의 코드를 실행하지 않는다.

Conversation state는 text-only pair가 아니라 system/user/assistant/tool message와 multimodal
content part, assistant tool call을 표현할 수 있어야 한다.

### 6. structured output은 tool calling과 별도 control이다

`request_parameters.response_format.allowed_types`에 따라 Text / JSON object / JSON schema를
표시한다. JSON schema는 server가 광고한 depth/property/string/strict 한도를 그대로 사용해
기본적인 client validation과 도움말을 제공한다.

Function calling은 중간 action request이고 structured output은 최종 response format이므로
UI와 state에서 별도 기능으로 유지한다.

### 7. send-time request context를 turn에 보존한다

각 exchange는 응답 데이터뿐 아니라 send 시점의 다음 snapshot을 메모리에 보존한다.

- public model id
- backend
- capability/input-modality snapshot
- 실제 전송한 request parameter
- request_id
- latency/usage

profile 전환 뒤에도 과거 응답의 실행 조건을 화면에서 확인할 수 있어야 한다. API key와
conversation/request snapshot은 기존과 같이 browser persistent storage나 서버에 저장하지 않는다.

### 8. model switch 뒤 capability cache를 즉시 무효화한다

Console에서 Main Model switch operation이 terminal 상태가 되면 `public-models` query도
invalidate한다. profile 전환으로 request parameter/modality/tool policy가 달라졌는데 30초
stale cache가 이전 control을 보여 주는 상태를 허용하지 않는다.

### 9. Scalar와 Console의 책임을 유지한다

Scalar는 전체 OpenAPI reference와 임의 request construction을 맡는다. Console Chat은
일상적인 model interaction과 capability verification을 맡는다. Responses API UI, API 전체
request builder, Grafana 기능을 복제하지 않는다.

Scalar는 same-origin vendored asset으로 유지하고 on-prem/air-gap 배포에서 Agent upload,
외부 default font와 같은 런타임 egress를 명시적으로 비활성화한다.

## Consequences

| Positive | Negative |
|---|---|
| profile/backend 차이를 UI 하드코딩 없이 실제 public contract에서 따라간다. | frontend state와 pure normalization logic이 기존 text-only 화면보다 커진다. |
| tools, multimodal, structured output을 실제 client와 같은 Gateway 경로에서 검증한다. | 브라우저가 처리하는 local file/base64 메모리 사용을 관리해야 한다. |
| send-time request context로 profile 전환 뒤에도 과거 결과의 조건을 추적할 수 있다. | 한 exchange가 보존하는 in-memory metadata가 늘어난다. |
| Scalar와 Chat의 책임이 겹치지 않은 채 operator UX가 개선된다. | complex parameter는 dedicated control을 지속적으로 유지해야 한다. |

## Operational impact

Chat playground 요청은 기존과 같이 public API 요청이며 admission, metrics, traffic summary,
access log에 일반 client와 같은 방식으로 기록된다. Tool simulator는 외부 function을 실행하지
않는다. Multimodal content는 별도 upload store를 만들지 않고 기존 Gateway body/media limit을
그대로 적용받는다.

## Migration notes

- ADR-0041의 scope decision을 이 ADR이 대체한다. 공개 API client, same-origin, 메모리 보관
  원칙은 유지한다.
- 기존 text conversation state는 multimodal/tool message를 표현하는 typed state로 단계적으로
  이동한다.
- Responses API UI는 이번 migration 범위에 포함하지 않는다.
- Scalar config/version 변경은 Chat implementation과 분리한 작은 PR에서 검증한다.

## Related

- [ADR-0027](0027-control-plane-runtime-configuration-and-console-boundary.md)
- [ADR-0040](0040-control-plane-korean-capability-ux.md)
- [ADR-0041](0041-console-chat-verification-surface.md)
- [Control Plane Chat Playground 설계](../reference/control_plane_chat_playground.md)
- Issue #211
