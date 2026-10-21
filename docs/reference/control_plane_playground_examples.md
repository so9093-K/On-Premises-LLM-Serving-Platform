# Playground 예제로 시작하기

Control Plane Playground의 Chat 작업 화면은 공개 `/v1/models`와 `/v1/chat/completions`를 그대로 사용한다.
이 페이지는 첫 사용자가 모델의 기능을 쉽게 확인할 수 있도록 하는 **입력 구성 도우미**이며,
별도 모델 실행 엔진이나 API authority가 아니다.

## 사용 방법

1. **Playground**를 열어 상단에서 현재 모델과 지원 기능을 확인한다. 모델 선택이 필요한 배포에서는 여기서 바꿀 수 있다.
2. **예제로 시작하기**에서 짧은 카드를 선택한다. 예제 입력과 첨부를 미리 확인하고, 시스템 프롬프트/JSON Schema 원문은 필요한 경우 펼친다.
3. **입력에 적용**을 선택한다. 작성 중이던 입력·설정이 있다면 교체 확인을 거친다.
4. 입력창 옆의 예제 시작 표시와 첨부를 확인하고, 필요하면 내용을 수정한 뒤 **보내기**로 실제 공개 Chat API를 호출한다.
5. 응답, 요청 지표, 요청 당시 설정과 Request ID를 확인한다. 문서 기능이 활성화된 배포 환경에서는 완료된 요청에서 Bootstrap이 제공한 Scalar API 문서로 이동할 수 있다.

예제 **선택과 적용은 추론 요청을 보내지 않는다**. 전송을 눌러야 기존 Gateway로 요청한다.
대화 시작 이후에도 상단의 **예제 보기**로 카탈로그를 열 수 있다.
예제로 시작했음을 입력창 근처에만 짧게 표시한다. 프롬프트나 첨부를 수정해도 출발 예제의 기록이라는 의미이며, 전송하거나 모델을 변경하면 사라진다.
모델 변경으로 기존 대화가 유지되거나 작성 중인 첨부 파일·일부 요청 설정이 바뀔 때는 변경 전 확인을 요구한다.
기존 대화에 대상 모델이 지원하지 않는 멀티모달 첨부 또는 Tool Calling 이력이 있으면 그대로 이어가지 않으며, **대화 지우고 변경**을 명시적으로 선택해야 한다. 모델별 숫자 제한을 벗어난 요청 설정은 전환 계획에서 초기화하고 그 영향을 확인한다. 호환 가능한 이력은 유지한다.

전송을 마친 요청 아래 **코드로 사용하기**에서 실제 요청 JSON과 재현용 Python/Node.js/cURL 예제를 가져올 수 있습니다. 예제를 적용한 현재 입력이 아니라 **실제로 보낸 요청**을 기준으로 합니다. [개발 프로젝트 연동 가이드](playground_integration.md)를 참고하세요.

## 제공 예제

| 예제 | 필요 조건 | 적용하는 내용 |
|---|---|---|
| 한국어 요약 | Chat | User Prompt |
| 그래프 분석 | Chat, Image | User Prompt, `sample-chart.png` |
| 주문서 정보 추출 | Chat, Image | User Prompt, `sample-order.png` |
| 문서 해석 | Chat, Image (PNG 약 112 KiB 이상 허용) | User Prompt, `sample-diagram.png` |
| 오디오 분석 | Chat, Audio, WAV 허용 | User Prompt, `sample-audio.wav` |
| 영상 분석 | Chat, Video, WebM·8초·640×360 허용 | User Prompt, `sample-video.webm` |
| 역할 지정 | Chat | System Prompt, User Prompt |
| JSON 정보 추출 | Chat, JSON Schema response_format | User Prompt, JSON Schema |

모델별 가용성은 `/v1/models`의 `capabilities`, `input_modalities`,
`request_parameters`를 프런트엔드가 해석한 기존 `chatControls`에 따라 결정한다.
지원되지 않는 예제는 이유를 표시하고 적용을 막는다. 이미지·오디오·영상의 정적 크기와 모델별 MIME/확장자·첨부 개수 제한, JSON Schema 제약은 예제 선택 전에 검사한다. 영상 예제는 등록된 길이와 프레임 해상도도 공개 모델의 상한과 비교한다.
실제 파일 준비 과정에서는 기존 파일 검증으로 전체 대화 첨부 개수와 이미지 픽셀 수를 재확인한다.
Gateway가 최종 요청 검증의 authority다.

기존 대화가 있으면 System Prompt 또는 Structured Output이 바뀌는 예제를
자동으로 적용하지 않는다. 운영자가 기존 대화를 명시적으로 지워야 새 예제에 사용할 수 있다.
단순 텍스트·이미지·오디오·영상 예제는 기존 대화로 이어갈 수 있지만, 전체 대화의 미디어 제한을 그대로 적용한다.
오디오 미리보기 재생은 로컬 정적 파일만 사용하며 추론 요청을 발생시키지 않는다. 「음성 대본 보기」는 접근성을 위해 제공하지만 모델 요청에는 포함하지 않는다.

예제 적용 시 작성 중인 메시지·첨부와 시스템 프롬프트·응답 형식·Tool 정의가
해당 예제로 바뀐다. **고급 Sampling 설정과 완료된 대화는 유지한다.**
첨부 자산 획득과 실제 Chat 요청 preflight가 실패하면 기존 입력을 유지한다.
예제 파일 준비 중 요청 설정·대화·모델이 변경되거나 예제 화면을 닫으면
진행 중이던 예제 적용을 취소하며, 늦게 도착한 파일 결과를 반영하지 않는다.
예제가 적용되면 입력창이 다시 활성화된 후 키보드 포커스를 이동한다.
대화 중 다른 메뉴에 다녀와도 예제 갤러리는 자동으로 다시 열리지 않는다.
API Key와 대화는 기존과 같이 탭 메모리에만 남고 영구 저장하지 않는다.

## 공개 샘플 자산과 오프라인 경계

샘플 원본은 `assets/demos/inputs/`에 있으며,
프런트엔드 번들에 동일한 PNG/WAV/WebM 데이터를 로컬 정적 자산으로 포함한다.
브라우저는 현재 Console의 same-origin 정적 경로에서만 샘플을 불러온다.
외부 URL fetch, 제3자 저장소 업로드 및 새로운 API endpoint를 추가하지 않는다.

Vite가 이미지와 오디오 파일을 `asset-manifest.json`에 기록해야 Gateway의
`admin_console.py` 파일 허용 목록에서 제공할 수 있다.
따라서 `make console-build` 뒤 `make console-check`로 생성 파일 일치를 확인하고,
실제 Console 브라우저에서 이미지·오디오 로딩 및 WAV 재생을 확인한다.
오디오 원본의 CC0 사용 조건과 녹음·가공 근거는 [Playground 오디오 샘플](playground_audio_sample.md)에 기록한다.
영상의 제작·디코딩 근거와 동작 범위는 [영상 샘플 제작 및 검증](../resources/playground_video_validation.md)에 기록한다. 영상 예제는 자동 재생 없이 직접 재생·일시정지할 수 있고, 장면 설명을 펼쳐 확인할 수 있다. 무음 합성 영상의 시각적 변화를 질문하며 음성 이해·정확한 사건 시각이나 내부 프레임 샘플링의 정확도를 보증하지 않는다. 장면 설명은 모델 요청에 포함하지 않는다.

샘플들은 [기능 데모](feature_demos.md)의 실제 촬영 조건에 근거한 예시다.
별도의 정답률·처리량·Prompt Injection 탐지 성능을 보증하지 않는다.

## 검증 체크

- Text-only 모델에서 Image·Audio·JSON 예제 비활성화 및 이유 표시
- Audio 모델에서 허용 포맷·크기·첨부 개수 검사, 샘플 WAV 준비, 재생·대본 확인
- Video 모델에서 WebM·크기·개수·길이·해상도 검사, 무음 영상 재생과 실제 `video_url` 요청 및 JSON 내보내기 확인
- 오디오 요청의 `input_audio` 직렬화, 미지원 모델과 파일 획득 실패 시 원래 입력 유지
- Image/JSON 지원 모델에서 올바른 Prompt, Schema, 정적 샘플 적용
- 입력 교체 전 확인, 예제 선택 시 비실행, 기존 대화·API Key 보존
- Tool result 대기·stream 진행·파일 로딩 중 예제 적용 차단
- 모델 전환 뒤 오래된 이미지 비동기 로딩 결과 적용 차단
- 샘플 파일을 허용 목록과 Gateway media limit으로 재검증
- Desktop 1440×900, Mobile 390×844, Keyboard/Focus/Screen-reader 안내
- `make console-check`, `make check` 및 가능한 Target의 실제 inference 확인

## Risk 화면의 합성 예제

Risk 작업 화면은 Chat 예제와 별도로 합성 입력 예제를 제공한다. 원본은
`ui/control-plane/src/playgroundRiskExamples.json` 하나이며, 로컬 PII·Secret 검출기가
기대 신호를 실제로 반환하는지 `tests/unit/test_playground_risk_examples.py`가 검증한다.

| 예제 | 검사 | 기대 신호 |
|---|---|---|
| 연락처 정보 | PII 탐지 | `D2` (이메일·전화번호) |
| 설정 파일의 자격 증명 | Secret 탐지 | `D4`, `D5` |
| 지시 무시 시도 | Prompt Injection 탐지 (`/v1/models`가 Prompt 검사기를 공개하는 구성만) | `A1` (모델 판정이므로 보장하지 않음) |
| 일반 업무 문장 | 통합 Risk 평가 | 없음 |

이메일은 `example.com`, Access Key는 AWS 문서의 예제 키다. 예제 선택은 입력만 채우며
요청하지 않는다. Risk 결과는 신호와 완료 여부만 표시하고 입력을 결과에 복제하지 않는다.
작업 화면 구성과 결과 해석 원칙은 [ADR-0056](../adr/0056-playground-feature-workspaces.md)을 따른다.

## 범위 제외

Scalar API Reference 복제, Responses API 화면, Tool 자동 실행, API 코드 생성,
모델 병렬 비교, 평가/Benchmark, Runtime 및 GPU 정책 변경은 수행하지 않는다.
Embedding·Risk 작업 화면은 Chat 예제 갤러리를 공유하지 않으며, 코드 예제는 Chat의 ZIP 대신 전송 바이트를 담은 단일 파일로 제공한다.

관련 설계: [ADR-0047](../adr/0047-control-plane-capability-aware-chat-playground.md) ·
[운영자 작업 중심 UX](control_plane_operator_ux.md).
