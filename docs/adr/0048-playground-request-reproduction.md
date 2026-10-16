# ADR-0048: Playground 전송 요청을 재현 가능한 개발 코드로 제공한다

## Status

Accepted

## Context

Playground의 요청 생성기는 공개 모델 capability에 따라 실제 Chat API 요청을 구성한다.
하지만 기존 Exchange 진단 정보는 messages를 보존하지 않으므로 과거 요청을 개발 프로젝트로
가져올 수 없었다. Scalar의 정적 예제는 실제 실행한 요청과 동일하지 않다.

## Decision

1. buildChatRequest와 buildToolResultRequest가 요청 구조의 Source of Truth로 남는다. 클라이언트가 사용하는 Chat Endpoint는 OpenAPI에 타입으로 연결된 공통 상수를 사용한다.
2. ChatSessionContext가 JSON을 단 한 번 직렬화하고, 같은 문자열을 public
   Gateway 전송과 해당 Exchange의 requestJson 기록에 모두 사용한다. 호출부는 별도 body와 직렬화 문자열을 각각 전달하지 않고 준비된 요청 한 개를 전달한다.
3. 요청의 내보내기는 원본을 다시 생성하지 않고, 기록한 문자열에서만 수행한다.
   다른 모델로 전환하거나 현재 Playground 설정을 바꿔도 과거 데이터는 바뀌지 않는다.
4. 사용자 명령으로만 요청 JSON, Python, Node.js, cURL 실행 예제, README를 생성한다.
   예제들은 원본 요청 파일을 그대로 HTTP로 전송하며 새로운 API endpoint를 만들지 않는다.
   비표준 모델 파라미터를 SDK 호환성 때문에 임의 제거하지 않는다.
5. Scalar는 표준 API 명세와 정적 SDK 샘플을 계속 소유한다. Playground는 특정 전송
   요청의 코드화를 담당하고 범용 Request Builder나 자동 Tool Executor를 복제하지 않는다.
6. 브라우저 탭 메모리 수명, 인증 header와 관리자 credential의 분리, 외부 저장 금지,
   기존 Gateway 검증과 admission을 유지한다. 내보낸 원본에는 사용자가 보낸 텍스트,
   이미지, 오디오, 비디오, 도구 입력이 포함될 수 있으므로 민감도 안내가 필요하다.
7. 생성 클라이언트는 Gateway SSE 오류와 완료 신호 누락을 실패로 처리하며, 기존 `STREAM_INCOMPLETE` 의미를 재사용한다. 새 서버 오류 코드는 만들지 않는다.
8. 전송 요청의 재현성은 모델 결과의 결정성이나 과거 프로필의 영구 사용 가능성을 뜻하지
   않는다. 실패 또는 중단된 요청은 실행 성공처럼 표시하지 않는다.

## Consequences

- 미디어와 확장 파라미터가 포함된 실제 Request Body를 손실 없이 내보낼 수 있다.
- Exchange의 직렬화 요청 보관으로 탭 메모리 사용량이 증가할 수 있다.
  기존 모델 요청 크기와 미디어 제한은 Gateway가 계속 관리한다.
- 검증은 실제 wire body와 export JSON의 일치, 실행된 언어별 HTTP 클라이언트의
  재전송 동등성, 브라우저 파일 다운로드와 접근성 확인을 중심으로 한다.

## Related

- [ADR-0047](0047-control-plane-capability-aware-chat-playground.md)
- [Developer guide](../reference/playground_integration.md)
