# 단계별 가이드 화면 촬영 정보

촬영일: **2026-10-19** · Linux/NVIDIA 실제 기동·추론·인증 · 실패 주입 화면은 별도 표시

## 환경

- 기반 main: `764d9d53`. UI·Gateway·Controller·Risk·vLLM 이미지의 source revision:
  `dc45450aa842e7272e78d5b86378f7af73b01617` (가이드 본문 포함, 해당 시점 clean build).
  촬영 중 가이드·화면 자산 및 호스트 RAW 로그 조회 수정이 있었으며 제품 UI·추론 코드는 변경하지 않았다.
- served bundle: `index-Dl0kbL1U.js`.
- Platform image: `sha256:7202b2b2fd62bec2d432bdbf560e6717cc990d4901db77e45d2d84bf3db8162d`.
- Unified vLLM image: `sha256:be579fc090690db9283e3b65b86a2c2be879efefa760375f972857857d622475`.
  image metadata의 vLLM `0.30.0`, Transformers `5.17.0`, Hugging Face Hub `1.32.0`.
- target: `linux-nvidia-dynamic`, RTX 4090 24GB, profile `gemma4-e4b-it`, variant `rtx4090-24gb`.
- 실제 Runtime argv의 model revision: `ee0ef6023621cff504d758262d4e04895a5af4a2` (`google/gemma-4-E4B-it`).
- 기존 `.env`와 모델 캐시로 `make up TARGET=linux-nvidia-dynamic ACCESS=local`을 실행했다.
  source 변경에 따른 이미지 빌드는 포함하지만 신규 호스트 설치나 최초 모델 다운로드를 검증한 것은 아니다.
- Chromium `156.0.8078.4`, `ko-KR`, `Asia/Seoul`, dark theme, device scale 1, zoom 100%.
  일반 UI/출력은 1440×900 viewport PNG다. 요청 내보내기 패널은 1440×1200 viewport에서
  해당 실제 DOM 영역을 캡처했다. 별도 픽셀 합성·상태·응답·수치 수정은 없다.
- 관리자 인증은 같은 Platform image의 별도 loopback Gateway(19400)에 `private` 인증 정책과
  임시 저장소를 적용했다. 기존 local Gateway의 접근 정책은 바꾸지 않았다.
  촬영 파일에 키·내부 IP·민감 로그가 없는지 이미지별로 검수했다.

## 화면별 의미

| 화면 | 수행·관찰 | 해석 범위 |
|---|---|---|
| [재기동 출력](startup-output.png) | 실제 `make up` 마지막 주소 출력과 `make status`의 stdout/stderr를 발췌해 브라우저에서 렌더링 | 터미널 앱 자체의 스크린샷이 아니다. 기존 캐시 재기동이며 중지된 dependency의 Attention과 종료 코드도 그대로 표시 |
| [관리자 인증](admin-auth.png) | 별도 인증 Gateway의 실제 빈 입력 폼 | 키 입력 전. API 사용자 키·Admin 키의 올바른 조합은 200, 교차 사용은 401을 별도로 확인 |
| [요청 전](playground-before.png) | 한국어 요약 예제 선택 | 입력 적용·추론 실행 전 |
| [요청 후](playground-after.png) | 예제를 입력에 적용하고 실제 streaming 응답 확인 | 표시된 문구·지연·토큰은 한 요청의 실제 결과이며 benchmark가 아님 |
| [요청 내보내기](request-export.png) | 위 실제 응답의 코드 패널, ZIP 다운로드 | 원본 request.json으로 Python/Node/cURL 재현 및 Python SDK 호출 확인 |
| [Runtime 상태](runtime-states.png) | Main 실행 중, Embedding 2종 중지/컨테이너 생성됨, 탐지기 정책상 제외 | GPU 비율은 예약 정책. 정책 제외는 고장·다른 target 미지원과 다름 |
| [API·SDK 출력](api-sdk-output.png) | 가이드의 cURL 모델 조회·일반·Streaming 및 Python SDK 2.54.0 예제를 실제 실행한 결과를 렌더링 | 가이드 입력의 실제 모델 응답. 임의 성공 응답을 삽입하지 않음 |
| [스트림 중단 테스트](stream-incomplete-injected.png) | 브라우저 route에서 `[DONE]` 없는 SSE를 반환해 `STREAM_INCOMPLETE` 확인 | **테스트 주입**. 부분 응답·request ID·지연은 테스트 데이터. 실제 GPU 장애·모델 추론·성능 자료가 아님 |

Playground는 저장소의 공개용 **한국어 요약** 예제를 사용했다. 스트림 중단 테스트는
“문서 검증: 스트림 중단 예시” 입력에 “문서 검증용 부분 응답입니다.”를 주입했다.
API/SDK는 가이드의 “플랫폼 테스트입니다. 짧게 인사해 주세요.” 입력을 사용했다.
원본 요청 ZIP·실행 로그는 로컬 무시 경로에 보관하며 인증값을 문서나 이미지에 포함하지 않았다.
이번 검증은 Mac·외부 static Runtime 실행, Main profile 전환, 전체 supporting Runtime 동시 상주 검증을 포함하지 않는다.
