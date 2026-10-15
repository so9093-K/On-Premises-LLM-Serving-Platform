# Playground 예제로 시작하기

Control Plane의 Playground는 공개 `/v1/models`와 `/v1/chat/completions`를 그대로 사용한다.
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

## 제공 예제

| 예제 | 필요 조건 | 적용하는 내용 |
|---|---|---|
| 한국어 요약 | Chat | User Prompt |
| 그래프 분석 | Chat, Image | User Prompt, `sample-chart.png` |
| 주문서 정보 추출 | Chat, Image | User Prompt, `sample-order.png` |
| 역할 지정 | Chat | System Prompt, User Prompt |
| JSON 정보 추출 | Chat, JSON Schema response_format | User Prompt, JSON Schema |

모델별 가용성은 `/v1/models`의 `capabilities`, `input_modalities`,
`request_parameters`를 프런트엔드가 해석한 기존 `chatControls`에 따라 결정한다.
지원되지 않는 예제는 이유를 표시하고 적용을 막는다. 이미지의 정적 크기 제한과
JSON Schema 제약은 예제 선택 전에 검사하고, 실제 이미지 픽셀 수·대화 전체 첨부
제한은 이미지를 준비하는 과정에서 기존 요청 검증으로 재확인한다.
Gateway가 최종 요청 검증의 authority다.

기존 대화가 있으면 System Prompt 또는 Structured Output이 바뀌는 예제를
자동으로 적용하지 않는다. 운영자가 기존 대화를 명시적으로 지워야 새 예제에 사용할 수 있다.
단순 텍스트·이미지 예제는 기존 대화로 이어갈 수 있으나, 전체 대화의 이미지 제한도 그대로 적용한다.

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
프런트엔드 번들에 같은 이미지 데이터를 로컬 정적 자산으로 포함한다.
브라우저는 현재 Console의 same-origin 정적 경로에서만 샘플을 불러온다.
외부 URL fetch, 제3자 저장소 업로드 및 새로운 API endpoint를 추가하지 않는다.

Vite가 이미지 파일을 `asset-manifest.json`에 기록해야 Gateway의
`admin_console.py` 파일 허용 목록에서 제공할 수 있다.
따라서 `make console-build` 뒤 `make console-check`로 생성 파일 일치를 확인하고,
실제 Console 브라우저에서 이미지 로딩을 확인한다.

샘플들은 [기능 데모](feature_demos.md)의 실제 촬영 조건에 근거한 예시다.
별도의 정답률·처리량·Prompt Injection 탐지 성능을 보증하지 않는다.

## 검증 체크

- Text-only 모델에서 Image·JSON 예제 비활성화 및 이유 표시
- Image/JSON 지원 모델에서 올바른 Prompt, Schema, 정적 샘플 적용
- 입력 교체 전 확인, 예제 선택 시 비실행, 기존 대화·API Key 보존
- Tool result 대기·stream 진행·파일 로딩 중 예제 적용 차단
- 모델 전환 뒤 오래된 이미지 비동기 로딩 결과 적용 차단
- 샘플 파일을 허용 목록과 Gateway media limit으로 재검증
- Desktop 1440×900, Mobile 390×844, Keyboard/Focus/Screen-reader 안내
- `make console-check`, `make check` 및 가능한 Target의 실제 inference 확인

## 범위 제외

Scalar API Reference 복제, Responses/Embedding용 별도 Playground, Tool 자동 실행,
API 코드 생성, 모델 병렬 비교, 평가/Benchmark, Runtime 및 GPU 정책 변경은 수행하지 않는다.

관련 설계: [ADR-0047](../adr/0047-control-plane-capability-aware-chat-playground.md) ·
[운영자 작업 중심 UX](control_plane_operator_ux.md).
