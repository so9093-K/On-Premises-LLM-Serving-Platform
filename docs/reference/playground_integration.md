# Playground 요청을 내 프로젝트에서 재현하기

Playground는 공개 `/v1/chat/completions`을 호출합니다. 각 요청의
**코드로 사용하기**에서 실제로 전송된 요청을 가져올 수 있습니다.
새로운 모델 API나 클라이언트 상태 저장 기능은 아닙니다.

## 사용 방법

1. Playground에서 지원 모델을 확인하고 텍스트, 미디어, Tools, JSON Schema 등
   원하는 입력을 작성한 뒤 **보내기**를 누릅니다.
2. 응답 아래 **코드로 사용하기**를 엽니다. 이 데이터는 전송 당시의
   요청을 기준으로 하므로 이후 설정이나 모델을 변경해도 바뀌지 않습니다.
3. **전체 예제 ZIP 받기**를 선택하면 아래 파일을 함께 받습니다.
   - `request.json`: 실제 HTTP 요청 본문 전체
   - `client.py`: Python 3 표준 라이브러리
   - `client.mjs`: Node.js 18 이상
   - `client.sh`: Bash와 cURL
   - `README.md`: 실행 및 보안 안내
4. **요청 JSON 복사**로 원본 전체를 클립보드에 복사할 수도 있습니다. 압축을 해제해 필요한 클라이언트와 `request.json`을 같은 폴더에 두고
   자신의 개발 환경에서 실행합니다. 단일 코드와 JSON 파일을 따로 복사·다운로드할 수도 있습니다.

## 연결 환경

Gateway에 접근 가능한 주소를 `GATEWAY_URL` 환경변수로 전달합니다.
별도 지정이 없으면 localhost의 9400 포트를 사용합니다. 인증이 켜진 배포에서는
일반 사용자용 토큰을 `API_KEY` 환경변수로 전달합니다.
관리자 토큰은 사용자 모델 호출에 사용하지 않습니다. cURL 스크립트의 `--fail-with-body` 사용에는 curl 7.76 이상이 필요합니다.

실행 명령은 `python3 client.py`, `node client.mjs`, `bash client.sh`
중 하나입니다. SDK 설치 없이 동일한 request.json을 HTTP로 전송합니다.
OpenAI SDK를 이용한 별도 통합 예제는 [API Reference](api_reference.md) 및
`/docs`의 Scalar에서 제공합니다.

## 재현 범위

| 입력 유형 | 내보내는 내용 |
|---|---|
| Text / Multi-turn | 전송 당시 시스템·사용자·Assistant 메시지 |
| Image / Audio / Video | 전송된 content part, data URL 또는 Base64 |
| Structured Output | 요청에서 실제 사용한 JSON Schema |
| Tool Calling | 도구 정의 및 해당 요청의 도구 결과 메시지 |
| Streaming | `stream`, `stream_options`과 기타 요청 파라미터 |

원본 파일은 비표준 `reasoning`, `top_k`, `min_p` 등의 확장 필드까지
동일하게 유지합니다. Streaming 예제는 SSE 원문을 출력하므로 실제 앱에서는
이벤트를 애플리케이션 형태로 해석하고 Tool 결과를 이어 보내는 처리가 필요합니다. 생성된 클라이언트는 Gateway의 SSE 오류 이벤트와 `[DONE]` 누락을 실패 상태로 처리합니다. Tool Calling은 모델이
요청한 함수를 자동으로 실행하지 않으며, 앱에서 별도의 실행 및 후속 요청
흐름을 구성해야 합니다.

## 보안과 실행 조건

요청 파일에는 프롬프트, 이전 대화, 이미지·오디오·비디오 원본과 민감정보가
포함될 수 있습니다. 기밀 데이터가 담긴 파일을 공개 저장소에 올리지 마세요.
인증에 사용한 Key는 요청 본문에 추가하지 않으며, 실행 환경에서 별도로
제공합니다. 브라우저 내 요청 기록은 기존의 탭 메모리 수명을 따릅니다.

`local-main`은 논리 모델 별칭입니다. 나중에 활성 모델과 정책이 바뀌면
같은 HTTP 요청을 보낼 수 있더라도 같은 응답이 보장되지는 않습니다.
실패하거나 중단된 요청을 내보낸 경우에도 성공으로 해석하지 마세요.

참고: [Playground 예제](control_plane_playground_examples.md),
[OpenAI 호환 범위](openai_compatibility.md),
[ADR-0048](../adr/0048-playground-request-reproduction.md).
