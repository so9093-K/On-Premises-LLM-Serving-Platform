# Playground 요청을 내 프로젝트에서 재현하기

Playground는 공개 `/v1/chat/completions`을 호출합니다. 각 요청의 **코드로 사용하기**는
전송된 HTTP 요청을 다시 보내는 **Exact Replay**와 애플리케이션 개발을 위한
**SDK Integration**을 구분합니다. 이 문서는 Chat 작업 화면을 다룹니다. Embedding·Retrieval·Risk 작업
화면은 같은 원칙으로 전송 바이트를 담은 cURL·Python·Node.js 단일 파일 예제를 제공합니다
([ADR-0056](../adr/0056-playground-feature-workspaces.md)).

## 입력부터 내보내기까지

1. Playground에서 현재 모델의 capability와 제한을 확인하고 텍스트, 미디어,
   JSON Schema 또는 Tool 정의를 지정합니다.
2. 실제 요청을 보낸 뒤 각 응답에서 **코드로 사용하기**를 엽니다.
   같은 입력을 나중에 재구성하는 것이 아니라 **해당 시점의 전송 바이트**를 보존합니다.
3. **전체 예제 ZIP 받기**를 이용하면 다음 파일을 얻습니다.

| 파일 | 용도 |
|---|---|
| `request.json` | 전송 당시 원본 Request Body. 프롬프트/미디어/Tool 정보 포함 |
| `client.py`, `client.mjs`, `client.sh` | Python/Node.js/cURL Exact Replay (별도 SDK 불필요) |
| `client_openai.py`, `client_openai.mjs` | OpenAI SDK 기반 애플리케이션 통합 예제 |
| `README.md` | 실행 환경, 보안 및 차이점 안내 |

4. 개발 환경의 Gateway 주소를 환경변수로 지정합니다.

```sh
export GATEWAY_URL=http://127.0.0.1:9400
# 인증된 배포는 공개 API 용 사용자 키만 지정합니다.
export API_KEY='your-public-api-key'
python3 client.py
node client.mjs
bash client.sh
```

Python 3 또는 Node.js 18 이상이 필요합니다. cURL 예제는
`--fail-with-body` 지원 버전(curl 7.76 이상)을 요구합니다.

## Exact Replay와 SDK Integration

원본을 정확히 검증하려면 위의 `client.py/mjs/sh`를 사용하세요.
모두 같은 `request.json`을 HTTP Body로 그대로 보냅니다.
Streaming 요청은 SSE 오류 이벤트와 `[DONE]` 누락을 실패로 처리합니다.
JSON Schema, `reasoning`, `top_k`, `min_p`, Tool 호출 결과 및
멀티모달 content part는 원본에서 제거하지 않습니다.

SDK 방식으로 자신의 서버 코드를 구성할 때는 아래 예제를 사용합니다.

```sh
pip install openai
python3 client_openai.py
# 또는
npm install openai
node client_openai.mjs
```

- Python은 OpenAI SDK의 표준 인자와 Gateway 확장 필드를 구분하고 확장 필드는
  `extra_body`를 통해 보냅니다.
- Node.js SDK는 요청 JSON을 Chat Completions API에 전달합니다.
- 코드에는 Streaming delta 소비, Tool 호출의 인자 확인, Structured Output JSON
  파싱 예제가 포함됩니다. 실제 Tool 함수 실행기는 포함하지 않습니다.
- SDK는 HTTP 헤더·기본 인자·Streaming 응답 처리를 조정할 수 있습니다.
  **SDK 예제의 요청 바이트 동등성은 보장하지 않습니다.**

Streaming 상태에서 Tool 함수의 arguments는 여러 delta에 분할되어 올 수 있습니다. 생성된 SDK 예제는 `tool_call.index`를 기준으로 조각을 합쳐 실제 실행 전 확인하도록 합니다.

실제 Tool 실행은 함수 허용 목록, 스키마/인자 검증, 권한·시간제한, 모델의
`tool_call_id`와 결과를 연결하는 후속 API 요청을 직접 구현해야 합니다.
모델이 임의로 만든 명령을 무조건 실행하지 마세요. SDK 예제의 단일 요청으로
완성된 Tool round trip이 만들어지는 것은 아닙니다.

## 큰 파일과 UI 응답성

요청 보관소는 탭 메모리 수명을 따르며, 큰 Base64와 긴 대화 텍스트를 요청마다 복제하지 않고 공유 세그먼트를 사용합니다.
줄바꿈·따옴표·백슬래시가 포함된 대화도 청크 단위 JSON 이스케이프로
실제 전송 바이트와 동일하게 재현합니다. 아카이브 생성은 청크 단위 비동기 ZIP64 쓰기를
수행하고 저장 속도에 맞춰 기다리며 진행률과 취소 기능을 제공합니다.

- **64 MiB 이하의 최종 파일:** 일반 다운로드 호환 경로
- **64 MiB 초과:** 지원 브라우저에서 파일 저장 위치를 명시적으로 선택하고
  스트리밍으로 직접 저장합니다.
- **대용량 저장 API 미지원:** 제한 이유를 알리고 실패합니다.
  용량이 충분하다는 가정만으로 브라우저 메모리에 무제한으로 누적하지 않습니다.
대용량 직접 저장을 지원하지 않는 브라우저에서는 제한을 다운로드 전에 안내하며
사용할 수 없는 저장 버튼을 비활성화합니다.

JSON 클립보드 복사는 전체 문자열 복제가 필요한 기능이므로 1 MiB까지
지원합니다. 그보다 크면 JSON 파일 다운로드 경로를 사용하세요.
File System Access API는 브라우저와 보안 컨텍스트에 따라 제한될 수 있습니다.

## 자원 수명과 보안

- `request.json`과 ZIP에는 이전 대화, 미디어 Base64, 기밀정보 및 Tool 인자가
  포함될 수 있습니다. 공개 저장소에 올리기 전 반드시 내용을 확인하세요.
- API Key는 다운로드 파일에 포함되지 않고 실행 환경변수로만 전달됩니다.
- 대화·첨부·Request Receipt는 서버·로컬 브라우저 영구 저장소에 기록하지 않습니다.
  대화 삭제나 Console 종료는 보관소의 참조를 해제하고 진행 중인 작업을 취소합니다.
- 현재 활성 모델이 `local-main`의 대상 모델을 바꾸면 동일 요청으로도 응답이
  달라질 수 있습니다. 모델 출력 결정성은 보장되지 않습니다.
- 사용자가 직접 저장한 파일의 수명은 다운로드 이후 사용자가 관리합니다.

관련: [API Reference](api_reference.md),
[OpenAI 호환 범위](openai_compatibility.md),
[ADR-0048](../adr/0048-playground-request-reproduction.md),
[ADR-0049](../adr/0049-playground-request-receipts-streaming-export.md).
