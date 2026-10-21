# ADR-0056: Playground는 배포 기능별 작업 화면으로 구성한다

## Status

Accepted

- Extends: [ADR-0047](0047-control-plane-capability-aware-chat-playground.md)

## Context

Control Plane Playground는 Chat Completions 중심으로 설계됐고 메뉴는 `chat` feature가
있을 때만 보였다. 그러나 Gateway는 이미 `/v1/embeddings`와 PII·Secret·Prompt Risk
detector, 통합 Risk 평가를 공개 API로 제공한다. 이 기능들을 확인하려면 Scalar에서
요청 본문을 직접 만들어야 했다.

특히 `linux-core`는 `chat=false`, `risk=true`다. Chat 화면에 Risk 패널만 추가하면
GPU나 모델 없이 운영하는 Core에서는 기본 제공 PII·Secret 탐지를 Console에서 확인할
방법이 없다.

Embedding과 Risk는 Chat 모델의 옵션이 아니다. Embedding은 별도 모델과 벡터 결과를,
Risk detector는 샘플링 파라미터 없이 신호와 완료 여부를 반환한다. Chat의 모델 목록과
설정 UI에 섞으면 각 기능의 계약을 잘못 표현한다.

## Decision

### 1. Playground 메뉴는 공개 요청 기능의 합집합으로 노출한다

`chat`, `embeddings`, `risk` 중 하나라도 활성화된 Deployment Target은 Playground를
제공한다. 내부의 작업 화면은 각 feature가 있을 때만 열린다. 메뉴·Route·작업 화면의
가용 여부는 기존과 같이 Bootstrap의 `deployment.features`가 소유한다.

| Target | Chat | Embedding | Risk |
|---|:---:|:---:|:---:|
| `linux-core` | — | — | ✓ |
| `linux-cpu-static`, `linux-cpu-managed`, `linux-adaptive` | ✓ | — | ✓ |
| `linux-nvidia-dynamic` | ✓ | ✓ | ✓ |
| `linux-nvidia-static`, `macos-metal-static` | ✓ | — | ✓ |

작업 화면은 `/admin/console/playground/{chat|embeddings|risk}`이며 이전
`/admin/console/chat`은 Chat 작업 화면으로 이동한다.

### 2. 각 작업 화면은 기존 공개 API와 공개 메타데이터만 사용한다

새 Gateway endpoint, Console 전용 proxy, 서버 저장소를 추가하지 않는다. API 키는
Chat과 같은 사용자 API 키를 탭 메모리에서 공유하며 관리자 키를 공개 API에 보내지 않는다.

- **Embedding**: `/v1/models`의 `capabilities`에 `embeddings`가 있는 모델만 제공하고,
  차원은 `request_parameters.dimensions`에서 읽는다. 두 문장 유사도는 두 입력을 하나의
  `/v1/embeddings` 요청에 담아 같은 모델이 만든 벡터끼리만 계산한다. 기본 화면은
  벡터 일부와 차원·Usage·Request ID를 보여 주고 원본 JSON은 펼쳐서 확인한다.
- **Risk**: PII·Secret·통합 평가는 `risk`, Prompt Injection detector는
  `prompt_detection` feature가 있을 때만 제공한다. 모델 샘플링 설정은 표시하지 않는다.

### 3. Risk 결과는 신호와 완료 여부로만 해석한다

ADR-0002의 Signal-only 계약을 화면에서도 유지한다. 허용·차단 같은 판정을 만들지 않는다.
API Reference의 안전한 해석 조건과 같이 `status=completed`,
`assessment_complete=true`, `system_signal_detected=false`, `risk_detected=false`가
모두 참일 때만 "탐지된 신호 없음"으로 표시한다. HTTP 200이어도 `partial`·`failed`이거나
시스템 신호가 있으면 미완료로 표시한다.

### 4. 민감한 입력을 화면 밖으로 옮기지 않는다

Risk 예제는 `example.com` 주소와 공개 문서의 예제 키 같은 합성 값만 사용한다. 예제는
로컬 검출기가 기대 신호를 실제로 반환하는지 테스트로 확인한다. 예제 적용은 요청을
보내지 않는다.

Embedding·Risk의 입력과 결과는 해당 작업 화면의 상태에만 둔다. 다른 화면으로 이동하면
사라지며 브라우저 저장소, 요청 내보내기, 서버에 저장하지 않는다. Risk 결과는 응답의 코드·
항목·개수만 표시하고 입력을 복제하지 않는다. Gateway의 선택적 요청 본문 로깅이 켜진
배포에서는 마스킹된 미리보기가 남을 수 있음을 화면에 안내한다.

## Consequences

| Positive | Negative |
|---|---|
| GPU 없는 Core에서도 기본 PII·Secret 탐지를 Console에서 확인한다. | Playground 상위 화면과 작업 화면 사이의 Route 계층이 생긴다. |
| 기능별로 다른 결과 의미(벡터·신호)를 Chat 설정과 섞지 않고 표현한다. | Embedding·Risk 결과는 화면 이동 시 사라지므로 비교하려면 다시 실행해야 한다. |
| 기존 공개 API와 인증 경계를 재사용하므로 서버 계약이 늘지 않는다. | 작업 화면별 순수 해석 로직과 Browser 검증을 유지해야 한다. |

## Operational impact

작업 화면의 요청은 일반 client와 같은 공개 API 요청이며 Admission, metric, access log,
요청 집계에 그대로 기록된다. Embedding Runtime이 중지된 배포에서는 Gateway의
`MODEL_UNAVAILABLE` 오류를 그대로 표시한다.

## Migration notes

- 이전 `/admin/console/chat` 북마크는 `/admin/console/playground/chat`으로 이동한다.
- Retrieval, Responses API, 모델 병렬 비교, 요청 내보내기의 Embedding·Risk 확장은 이 결정의
  범위가 아니다.

## Related

- [ADR-0002](0002-signal-only-risk-contract.md)
- [ADR-0027](0027-control-plane-runtime-configuration-and-console-boundary.md)
- [ADR-0047](0047-control-plane-capability-aware-chat-playground.md)
- [ADR-0053](0053-model-optional-deployment-and-cpu-static-serving.md)
- [Playground 예제](../reference/control_plane_playground_examples.md)
