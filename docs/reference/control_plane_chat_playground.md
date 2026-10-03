# Control Plane Chat Playground 설계

이 문서는 Issue #211 / ADR-0047의 구현 명세다. 목표는 Console을 별도 serving authority로
만들지 않고 현재 Gateway public model contract를 정확하게 보여 주는 것이다.

## 종료선

이번 사이클은 Phase C까지 완료하면 끝난다.

1. Phase A: Scalar review, Chat IA/wireframe, capability mapping, ADR/PR plan
2. Phase B: Scalar hardening, capability/request context, parameters, multimodal,
   structured output, tool round trip
3. Phase C: frontend/API/profile regression, responsive/accessibility review,
   generated artifacts, `make check`, required GitHub CI

실제 Linux/vLLM과 macOS/MLX browser E2E qualification, Responses API UI, #195 execution-layer
변경은 별도 작업이다.

## Information architecture

Desktop:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 채팅 테스트                                           대화 지우기   │
│ 공개 /v1/chat/completions를 실제 Gateway 경로로 호출                │
├───────────────────────────────────────┬─────────────────────────────┤
│                                       │ Model                       │
│ conversation                          │ local-main · vllm-cuda      │
│                                       │ Text Image Audio Video      │
│ user / assistant / tool messages      │ Tools Reasoning JSON        │
│                                       │                             │
│                                       │ Basic                       │
│                                       │ Reasoning  [off/on]         │
│                                       │ Max output [default]        │
│                                       │ Streaming [on/off]          │
│                                       │                             │
│                                       │ ▸ Advanced                  │
│                                       │ sampling / penalties / diag │
│                                       │                             │
├───────────────────────────────────────┴─────────────────────────────┤
│ [+ attachment] [Tools] [Output format]                             │
│ 메시지를 입력하세요...                                      보내기 │
└─────────────────────────────────────────────────────────────────────┘
```

Narrow viewport에서는 settings/context를 conversation 위에 한 column으로 둔다. 기존
980px breakpoint를 시작점으로 사용하고 horizontal overflow를 만들지 않는다.

## Model contract normalization

Frontend의 public model type은 OpenAPI-derived response를 기준으로 최소 다음 값을 소비한다.

```text
id
backend
capabilities[]
input_modalities[]
request_limits{}
request_parameters{}
```

Raw parameter dictionary는 먼저 normalized control model로 바꾼다.

| 서버 계약 | UI 의미 |
|---|---|
| `type:number/integer` | numeric input |
| `min/max` | inclusive range |
| `min_exclusive/max_exclusive` | strict range; 경계값 거부 |
| `enum/allowed` | select/segmented choice |
| `const` | read-only value; 일반 knob로 만들지 않음 |
| `requires` | prerequisite가 만족될 때만 활성 |
| `aliases` | help/diagnostic metadata |
| `min_items/max_items` | list/tool count constraint |
| `properties` | dedicated/nested control metadata |

현재 public Chat surface의 분류:

### Basic

- `reasoning`
- `max_tokens`
- `stream`
- `stream_options.include_usage`는 streaming 종속 옵션

### Advanced sampling

- `temperature`
- `top_p`
- `top_k`
- `min_p`
- `presence_penalty`
- `frequency_penalty`
- `repetition_penalty`
- `stop`
- `seed`

### Read-only / conditional

- `n`: 현재 min=max=1이면 editable control 대신 고정 계약으로 표시
- `parallel_tool_calls`: `const=false`이면 read-only policy
- `top_logprobs`: `logprobs=true`일 때만 활성
- `user`: Gateway compatibility/drop surface이므로 일반 Chat UI에 노출하지 않음

### Dedicated

- `tools`
- `tool_choice`
- `response_format`
- `logit_bias`

## Capability examples

UI test fixture는 최소 세 종류를 고정한다.

### Linux Gemma

- tools: yes
- reasoning: yes
- structured output: text/json_object/json_schema
- tool choice: auto/none
- multimodal: active profile에 따라 text/image 또는 text/image/audio/video
- logprobs/logit_bias: yes

### Linux Qwen

- tools/reasoning: no
- structured output: yes
- text/image/audio/video
- logprobs/logit_bias: yes

### macOS Metal

- tools/reasoning: yes
- tool choice: auto/none/required/named
- structured output: current MTP profile에서는 미광고
- text/image
- presence/frequency penalty 등 Linux-only surface는 숨김

테스트는 profile id나 backend 이름을 조건으로 사용하지 않고 fixture의 public contract만 바꾼다.

## Conversation state

최종 state는 다음 의미를 표현할 수 있어야 한다.

```text
SystemMessage
UserMessage
  content: text | image | audio | video parts
AssistantMessage
  content
  reasoning
  tool_calls[]
ToolMessage
  tool_call_id
  content
```

기존 성공한 user/assistant pair만 history에 넣는 규칙은 tool path에서 확장한다. 실패 turn은
다음 request history에 넣지 않는다. 사용자가 중지했지만 usable assistant content가 있는 경우의
기존 동작은 유지하되 tool call이 미완료인 assistant turn은 continuation history로 쓰지 않는다.

## Multimodal

Attachment picker는 현재 model의 `input_modalities`에 있는 타입만 제공한다.

Client preflight:

- count <= `request_limits.<modality>.max_inputs`
- file bytes <= `max_bytes`
- image MIME <= `allowed_mime_types`
- audio extension/format <= `allowed_formats`
- data URL scheme만 생성

Image dimension은 browser decode로 확인 가능한 경우 `max_pixels`를 선제 적용한다.
Video frame count/duration/codec은 frontend에서 별도 decoder를 만들지 않고 Gateway authority에
맡긴다.

## Structured output

`response_format.allowed_types`를 그대로 사용한다.

- text
- json_object
- json_schema

JSON object가 `require_json_instruction=true`이면 UI에서 prompt에 JSON instruction이 필요함을
설명한다. JSON schema editor는 JSON parse와 server-advertised high-level limit을 선제 검사하고
최종 schema semantics는 Gateway가 검증한다.

## Tools

Tool definition은 function name/description/JSON schema를 입력한다. max tool count와
tool_choice option은 public contract를 따른다.

Assistant tool call을 받으면:

1. function name / arguments 표시
2. arguments JSON parse 상태 표시
3. operator가 tool result text/JSON 입력
4. 같은 `tool_call_id`로 `role=tool` message를 추가
5. assistant final response 요청

Console은 function을 실행하지 않는다.

## Request context

Exchange 생성 시 send-time snapshot을 저장한다.

```text
model_id
backend
capabilities
input_modalities
request_parameters_sent
request_id
started/first-token/finished
usage
```

실제 request JSON 보기/복사는 이 snapshot과 conversation serialization에서 만든 값을 사용한다.
secret/API key는 snapshot에 포함하지 않는다.

## Scalar

Scalar는 범용 API reference를 유지한다.

첫 구현 PR에서 검토할 config:

- Agent 명시적 disable
- default external fonts disable
- telemetry 명시적 disable
- schema section label을 Models와 혼동되지 않게 조정
- parameter default expansion 축소

버전 bump는 vendored bundle/SRI와 custom CSS selector를 같은 PR에서 검증할 수 있을 때만 한다.
CDN fallback은 만들지 않는다.

## Stale capability 방지

Main Model switch operation이 terminal이 되면 다음 query를 함께 invalidate한다.

```text
['main-model', 'status']
['main-model', 'profiles']
['public-models']
```

외부 client가 profile을 바꾸는 경우 Chat 화면의 explicit refresh 또는 bounded refetch 정책을
Phase B에서 검토하되, profile identity를 frontend가 추측해서 cache key로 만들지 않는다.

## PR plan

PR 수는 고정 목표가 아니며 ownership이 겹칠 때만 합친다.

1. `docs(control-plane)`: ADR-0047 + 이 설계 문서
2. `fix(docs)`: Scalar on-prem/docs hardening
3. `feat(control-plane)`: model capability + request context + stale refresh
4. `feat(control-plane)`: normalized Basic/Advanced parameter controls
5. `feat(control-plane)`: multimodal content parts
6. `feat(control-plane)`: structured output
7. `feat(control-plane)`: tool-call simulator/round trip
8. 필요 시 `test(control-plane)`: Phase C에서만 남은 cross-cutting stabilization

## Verification

각 PR은 자기 계약을 직접 증명한다. 일반 CI 결과를 PR 본문에 복제하지 않는다.

Frontend unit fixture:
- Linux Gemma / Qwen / Metal public model contract
- exclusive/inclusive numeric range
- const/requires dependency
- stream on/off
- request serialization
- media count/bytes/type
- structured response format
- tool call/result serialization
- send-time request snapshot
- profile switch query invalidation helper

Repository gate:
- `make check`
- generated OpenAPI/Console assets current
- existing Ruff `F/E9/PLE` only
- required GitHub CI: Ubuntu/macOS app-contract, Console, Platform image, CI Gate

Browser review:
- Chromium desktop 1440×900
- Chromium mobile 390×844
- keyboard-only composer/settings/tool-result flow
- visible focus and labels
- screen-reader meaningful names/live status
- reduced-motion cursor behavior
- no unexpected horizontal scroll or browser console error

새 Playwright/axe/jsdom foundation은 이 기능을 구현하기 위해 자동으로 도입하지 않는다. 반복 가능한
DOM/a11y regression이 실제 필요해지면 별도 tooling decision으로 다룬다.
