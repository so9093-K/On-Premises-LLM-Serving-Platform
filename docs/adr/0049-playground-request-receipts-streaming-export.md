# ADR-0049: Playground Request Receipt, 미디어 소유권 및 스트리밍 Export

## Status

Accepted

## Context

[ADR-0048](0048-playground-request-reproduction.md)은 실제 Gateway 전송 요청을 변경 없이 내보내는
계약을 도입했으나, 전체 요청 JSON을 매 Exchange에 보관하고 ZIP을 동기적으로 생성했다.
여러 턴에 같은 인라인 이미지·오디오가 포함되면 과거 요청 저장소에서도 Base64가 반복되고,
다운로드가 커지면 메인 스레드 작업·임시 버퍼가 제한 없이 증가할 수 있었다.

Console은 air-gap에서 동작하며 브라우저 탭 메모리 수명과 사용자 주도 Export를 유지한다.
기능 제약은 Gateway와 `GET /v1/models`가 소유한다.

## Decision

### 요청의 Source of Truth

- `buildChatRequest` / `buildToolResultRequest`가 Chat 메시지·파라미터를 계속 결정한다.
- `prepareChatRequest`는 `RequestReceipt`의 불변 세그먼트를 만들고, 그 세그먼트를
  이어 만든 문자열 **하나**를 HTTP Body로 전송한다. 같은 Receipt가 JSON·ZIP의 입력이다.
  외부 API로 전송할 문자열을 UI 상태로 다시 생성하지 않는다.
- 세그먼트는 작은 JSON 텍스트와 재사용 가능한 미디어·긴 대화 문자열의 불변 참조로 나뉜다.
  FileReader의 data URL/Base64는 JSON에서 추가 escape가 필요 없는 ASCII일 때만
  참조 대상으로 만든다. 긴 대화 문자열은 줄바꿈·따옴표·백슬래시·유효하지 않은
  UTF-16 값을 포함해도 원문을 공유하고, 실제 전송 바이트 생성 시 UTF-16 코드포인트
  경계를 보존하는 청크별 JSON escape를 적용한다.
- 요청 기록의 바이트 길이와 전송/내보내기 순서·내용은 같아야 한다.
  수신 모델 출력을 재현한다는 뜻은 아니다.

### 메모리 소유권·데이터 수명

- 브라우저 Shell의 `MediaDataRegistry`는 내용이 같은 미디어 문자열을 intern한다.
  대화·첨부 파일과 각 Receipt는 이를 공유하며 전체 JSON 원본을 별도 상태로 보관하지 않는다.
- 등록된 미디어의 소유 범위는 탭의 Chat 세션이다. 대화 전체 삭제 또는 Shell 종료 시
  registry를 초기화하고 미완료 전송·내보내기를 중단한다. 개별 콘텐츠 조각의 강제
  메모리 삭제를 브라우저 GC보다 먼저 보장하지 않는다.
- IndexedDB, OPFS, localStorage, sessionStorage, 별도 서버 저장 API를 도입하지 않는다.
  인증 키는 ZIP·JSON·생성 코드 원본에 저장하지 않는다.

### 아카이브와 저장 대상

- ZIP 생성은 **한 가지 스트리밍 ZIP64 STORE Writer**가 소유한다. 별도의 동기 ZIP
  포맷 구현을 병행하지 않는다. CRC32, Data Descriptor, ZIP64 중앙 디렉터리를
  사용하고 출력 사이즈·완료 및 실패를 검증한다.
- AsyncIterable 청크와 Writable Sink로 작업을 분리하고, 생산자가 sink의
  `write()`을 await하므로 저장 대상의 Backpressure를 따른다.
  길게 실행되는 브라우저 작업은 작은 청크마다 이벤트 루프에 양보한다.
  Worker로 데이터를 재복제하는 구조를 기본값으로 사용하지 않는다.
- 일반 다운로드 호환 경로는 명시적 상한 64 MiB를 따른다. 이는 기기 성능의
  추정값이 아니라 **브라우저 메모리에서 완성하는 데이터의 지원 범위**다.
- 이 범위를 넘으면 사용자 승인 `showSaveFilePicker` / FileSystemWritable
  스트림에 직접 기록한다. 미지원 환경에서는 실패 원인을 표시하며 대량 데이터를
  몰래 Blob에 쌓지 않는다. 취소·오류 때는 열린 파일 스트림을 abort한다.
  파일 선택 취소는 사용자 작업 취소로 취급한다.
- 취소·진행률·정리의 주인은 현재 Export 작업이다. 대화가 화면에서 사라지면
  컴포넌트가 해당 작업을 abort한다.

### 두 가지 개발자 출력 계약

- **Exact Replay**는 `request.json` 원문을 Python 표준 라이브러리, Node Fetch,
  cURL로 전송한다. Gateway SSE 오류·완료 신호 누락과 HTTP 상태 오류를 보존한다.
- **Application Integration**은 별도 OpenAI SDK 코드로, Streaming delta 소비,
  JSON 응답 처리, Tool 결과의 명시적 검증·후속 요청 필요성을 설명한다.
  SDK가 자체 정규화·기본 헤더를 적용할 수 있으므로 이를 Byte-identical Replay라고
  표현하지 않는다. Python에서 Gateway 비표준 파라미터는 `extra_body`로 전달한다.
- 모델별 capability, 실제 인수 제한은 계속 Gateway가 소유한다. 생성 코드가
  서버 정책이나 Tools 실행 권한을 새로 만들지 않는다.

## Consequences

- 이미 전송한 멀티턴 미디어 및 안전하게 공유 가능한 긴 대화 텍스트를 Exchange마다 별도의 전체 JSON으로 중복 저장하지 않는다.
  HTTP 요청을 위한 전송 문자열은 요청 수행 중 일시적으로 존재할 수 있다.
- 같은 파일을 네트워크로 다시 보낼 때 발생하는 대역폭·Gateway 비용은
  Chat Completions의 stateless 요청 계약이 소유하며 이 브라우저 저장 구조로 줄지 않는다.
- 작은 ZIP도 ZIP64 포맷을 사용한다. 수신 측 ZIP Reader가 ZIP64를 지원해야 한다.
  Python zipfile 및 실제 브라우저 다운로드 계약 테스트로 호환성을 보호한다.
- 브라우저 스트리밍 파일 API가 없는 환경에서 크기 상한을 넘는 내보내기는
  명시적으로 사용할 수 없다. 데이터 소실 또는 무제한 메모리 fallback을 선택하지 않는다.
- 메인 스레드의 작업을 청크화하고 양보하므로 불필요한 대형 Worker 문자열 복제를 피한다.
  런타임 메모리 피크 및 응답성은 파일 크기·대화 턴·브라우저 상태별로 계속 측정한다.

## Related

- [ADR-0047](0047-control-plane-capability-aware-chat-playground.md)
- [ADR-0048](0048-playground-request-reproduction.md)
- [프로젝트 연동 가이드](../reference/playground_integration.md)
