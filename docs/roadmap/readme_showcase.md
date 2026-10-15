# README 화면·데모 제작 명세

README는 제품을 이해하고 첫 요청을 실행하는 입구로 구성한다. 상세 계약은 기존 `docs/`가 소유한다.
이 문서는 README 개편의 문구, 촬영, 편집 및 공개 기준이다. 미완료 제작 항목은 마지막 체크리스트에서 추적한다.

## 1. 대상과 첫 화면

대상은 자체 인프라에서 모델 API를 제공하려는 개발자와, 모델·GPU·서비스를 운영하는 담당자다.
처음 방문한 사람이 "어떤 모델을 어디서 실행하고, 어떻게 호출하며, 무엇을 운영할 수 있는가"를 이해하게 한다.

권장 첫 화면 문구:

> # On-Premises LLM Serving Platform
> Run, serve, and operate AI models on your infrastructure.
>
> **Your models. Your infrastructure. One serving platform.**
>
> 다양한 환경에서 AI 모델을 실행하고, 하나의 API로 연결하고,
> Control Plane에서 상태·모델·리소스를 운영하세요.
>
> OpenAI-compatible API · Model Lifecycle · GPU Resource Control · Observability
>
> Linux / NVIDIA · Apple Silicon · Self-hosted

이 문구 바로 아래에는 실제 **운영 개요** 화면을 둔다. "기능은 Deployment Target에 따라 다릅니다"를
함께 표시한다. 플랫폼 전체 기능을 Apple Silicon에서도 모두 제공하는 것처럼 배치하지 않는다.
설치 시간은 모델 다운로드·빌드·장비에 따라 달라지므로 "5분 설치"는 약속하지 않는다.

## 2. README 정보 구조와 문구

| 순서 | 제목 | 사용자가 얻는 정보 | 상세 설명의 소유 문서 |
|---|---|---|---|
| Hero | 위 소개 문구 + 운영 개요 | 모델 API와 운영 UI를 함께 제공하는 플랫폼 | [개요](../01_overview.md) |
| 01 | What can you do? | 아래 세 가지 사용 결과와 실제 화면 | [운영 UX](../reference/control_plane_operator_ux.md) |
| 02 | See it in action | 실제 요청 → 변경 영향 검토 → 결과 확인 | [모델 운영](../06_model_operations.md) |
| 03 | How it works | Gateway, Runtime, Control Plane 관계 | [시스템 구성](../03_system_components.md) |
| 04 | Quick Start | 환경 선택, 실행, Console 접속, 첫 API 요청 | [실행 모드](../04_runtime_modes.md) |
| 05 | Deployment Targets & Capabilities | 지원 기능과 lifecycle 권한의 차이 | [target 선언](../../configs/deployment_targets.yaml) |
| 06 | Documentation & Development | API·설정·관측·검증·기여 문서로 이동 | [문서 목차](../README.md) |

핵심 기능의 공개 문구:

- **모델과 서비스 상태를 한눈에** — 운영 개요에서 현재 모델과 Runtime 상태, 최근 요청을 확인하세요.
- **실제 모델 응답을 테스트** — Playground에서 공개 API를 호출하고 응답과 요청 당시 설정을 확인하세요.
- **영향을 검토하고 모델을 변경** — 지원 기능과 자원 영향을 확인하고 전환 결과를 추적하세요.
  Linux/NVIDIA managed target의 기능임을 명시한다. 전환은 중단·실패·복구 가능성이 있다.

Runtime/GPU, 설정, Grafana·로그는 세 핵심 화면 아래에서 짧게 소개하고 해당 문서로 연결한다.
동일 운영 개요 이미지를 Hero와 기능 설명에서 크게 두 번 반복하지 않는다.

Quick Start는 기존 `make up TARGET=... ACCESS=local`과 `make status`, `make down`을 유지한다.
Console `/admin/console/`, API 문서 `/docs`, `local-main` Chat Completions 예제를 붙인다.
첫 API 예제에는 local access 기준임을 표시하고 인증 환경의 Bearer 사용법을 API 문서로 연결한다.
외부 Runtime의 URL은 **Gateway container에서 접근 가능한 주소**여야 한다. host loopback을 그대로
복사하는 static 예제를 추천하지 않는다. Python·Docker·NVIDIA driver/Container Toolkit 등 조건은
환경별로 요약하고 설치 상세를 링크한다. Hugging Face token은 실제 값을 문서·영상에 넣지 않는다.

아키텍처는 기존 `assets/ai_model_serving_system_architecture.png`를 사용하되,
현 구성과 대조한다. Source of Truth는 [설정 체계](../05_configuration.md)로 연결한다.
`make setup-dev`, `make app-check`, `make check`와 live Runtime 검증의 차이를 유지한다.
버전·변경 이력·기여·라이선스·제3자 고지를 하단에서 찾을 수 있게 한다.

## 3. 화면 목록

아래 경로는 `/admin/console/` 기준이다. 모든 화면은 같은 촬영 세션의 실제 UI를 사용한다.

| ID | 화면 / 경로 | 보여줄 결과 | 촬영 조건 | 배치 |
|---|---|---|---|---|
| S01 | 운영 개요 `/` | 활성 모델, Runtime 상태, 최근 실제 요청 | 공개용 요청을 수행한 뒤 집계 표시 대기 | Hero |
| S02 | Playground `/chat` | 짧은 실제 응답, 요청 설정, 응답 메타데이터 | 아래 공개 프롬프트 사용, streaming 완료 | 핵심 기능 |
| S03 | 메인 모델 `/main-model` | 현재 모델과 후보의 기능·자원 영향 | managed target, 실제 허용 후보 확인 | 핵심 기능 |
| S04 | 런타임과 GPU `/runtimes` | 실행 상태와 정책상 예약 | 예약값을 실측 VRAM으로 표현하지 않음 | 운영 심화 |
| S05 | 운영 활동 `/operations` | 실제 설정·Runtime·모델 변경 결과와 탐색 흐름 | 촬영 세션에서 발생한 기록만 확대 | 운영 심화 |
| S06 | 설정 `/configuration` | 현재 적용 값·출처·변경 결과 | 촬영용 Gateway의 실제 변경 | 운영 심화 |

Grafana 서비스 개요는 별도 관측 영상에서 추가 촬영한다.

기존 `control_plane_chat_test.webp`는 macOS의 이전 "채팅 테스트" UI다. 최신 Linux managed
대표 화면으로 재사용하지 않는다. 기존 Grafana/Scalar/로그 이미지는 재사용 전에 현재 UI와 노출 정보를
다시 확인한다. 화면이 없으면 깨진 이미지 링크나 모형을 실제 화면 자리에 넣지 않는다.

공개용 입력 예:

> 사내 AI 모델 API를 운영할 때 확인할 사항 세 가지를 한 문장씩 한국어로 알려주세요.

응답은 그대로 보존한다. 특정 답변·토큰 수·응답 시간을 만들거나 덮어쓰지 않는다.
필요하면 이 프롬프트로 짧은 요청을 몇 번 실행해 실제 최근 요청 집계를 확보한다.
인위적으로 넣은 DB 통계나 fixture가 있다면 해당 이미지와 영상에 "예시 데이터"를 표시한다.
실제 모델에 공개용 예시 질문을 보낸 경우에는 "공개용 예시 입력, 실제 모델 응답"으로 설명한다.

## 4. 촬영 기준

- Desktop: viewport 1440×900, device scale 1, browser zoom 100%, 동일 Chromium·테마·언어.
- GIF는 Chat 1280×800, API 뷰어 1280×900을 사용한다. 실제 촬영 조건은 [GIF 데모](../reference/feature_demos.md)에 기록한다.
- Mobile 확인: 390×844. README에서 이미지 축소 시 핵심 메시지를 캡션만으로도 읽을 수 있게 한다.
- Screenshot은 UI 내용 영역을 캡처한다. browser chrome, desktop 알림, 개발자 도구, 인증 입력 화면은 제외한다.
- 촬영 전 실제 served bundle과 source commit을 대조한다. stale image를 최신 UI라고 설명하지 않는다.
- 실험용 Gateway를 사용하면 연결한 실제 backend/target과 runtime을 촬영 기록에 명시한다.
- 로딩·스켈레톤이 끝나고 폰트가 로드된 뒤 촬영한다. 오류와 미지원 상태를 성공처럼 편집하지 않는다.
- API/Admin Key, token, private IP, 사용자 경로, 내부 hostname, 민감 로그·대화는 공개본에서 제외한다.
  필요한 가림은 범위를 명시하고 실제 상태·수치·결과는 수정하지 않는다. 인증은 녹화 전에 끝낸다.
- request ID는 예시 요청에서 생성된 것만 허용한다. 키와 혼동하지 않도록 필요한 화면에서만 보여 준다.
- `healthy`, `qualified`, `gate open`을 추론 성공이나 무장애 보증으로 합쳐 표현하지 않는다.
- 정책상 GPU 예약과 DCGM 실측 VRAM은 각 화면의 의미 그대로 표기한다. 지연은 단일 예시 요청값이다.
- 최종 이미지는 WebP 또는 PNG, 목표 500 KB 이하/장. 글자가 흐려지면 크기보다 가독성을 우선한다.
- 전체 화면과 확대 crop을 섞을 때 crop임을 설명한다. 스크린샷마다 목적을 설명하는 alt와 짧은 캡션을 제공한다.
- 원본 영상·로그·인증 상태는 Git에 넣지 않는다. 공개할 정리된 자산만 `assets/`에 추가한다.

촬영 기록에는 날짜, source commit, served asset, target, model/profile/revision, 해상도,
실제 입력, 실행 여부, 편집·가림 범위를 남긴다. 인증값 자체는 기록하지 않는다.

## 5. 90초 메인 데모 스토리보드

| 구간 | 화면과 행동 | 자막·전달 메시지 | 증명 범위 |
|---|---|---|---|
| 00–08 | 운영 개요, target와 활성 모델 확인 | Your models. Your infrastructure. | 실제 조회 시점의 상태 |
| 08–18 | 모델·서비스 상태와 최근 요청 확인 | 모델과 서비스 상태를 한눈에 | 조회 상태와 추론 성공을 구분 |
| 18–40 | Playground에 공개용 질문 전송, 응답 표시 | 하나의 공개 API로 실제 모델 응답 테스트 | 실요청·실응답, 임의 수치 없음 |
| 40–57 | 메인 모델에서 후보와 기능·자원 영향 확인 | 변경하기 전에 영향을 검토 | compatible/qualified·중단 가능성 표시 |
| 57–72 | 가능한 경우 전환 실행과 완료 결과 | 실제 전환 진행 및 결과 | 대기 생략은 "대기 구간 편집" 자막 |
| 72–83 | 성공한 경우 새 모델에 별도 요청 | 전환 후 실제 응답 확인 | 모델 전환 결과와 요청 성공을 각각 확인 |
| 83–90 | 운영 활동 → 문서·Quick Start 안내 | 운영 기록부터 API 문서까지 | 실제 기록 및 유효 링크 |

**전환 촬영 분기:** 호스트의 resource variant에서 서로 다른 두 profile이 실제 허용되고
검증 가능한지 먼저 확인한다. 현재 `rtx4090-24gb` override는 E4B에만 있으므로 다른 profile
전환 성공을 전제로 녹화하지 않는다. 후보가 허용되지 않으면 57–72초에 제한 이유를 보여 주고,
72–83초에는 현재 모델의 응답 확인으로 마무리한다. 제목·자막은 "전환 영향 검토"로 쓰며
"모델 전환 데모" 또는 "전환 성공"이라고 부르지 않는다. 전체 전환 시연은 적합한 host에서 별도 촬영한다.

90초는 편집 목표다. 실제 부팅·추론·전환이 90초 안에 끝난다는 약속이 아니다.
실시간 구간은 속도를 유지한다. 대기 생략·배속은 화면에 표시하고 실제 경과 시간과 혼동시키지 않는다.
최상단은 정적 이미지를 유지한다. 기능별 짧은 GIF는 소개 아래에 배치하고 정지 화면 링크를 함께 제공한다.
현재 이미지 분석 GIF를 README에 표시하며, OCR·시스템 프롬프트·임베딩은 [GIF 데모](../reference/feature_demos.md)로 연결한다.
90초 영상은 별도 제작할 경우 클릭 가능한 썸네일로 연결한다.
MP4(H.264, 1080p 이하, 30 fps) 공개본과 자막/텍스트 요약을 준비한다.
자막·제목용 공간은 녹화 편집에서 확보하고 제품 UI에 가짜 라벨을 삽입하지 않는다.
설치 데모와 운영 심화 영상은 실제 제작·업로드 후에만 링크한다.

## 6. Target별 표현 경계

| 범위 | Linux managed | Linux external | Apple Silicon |
|---|---|---|---|
| Main runtime | vLLM, 플랫폼 관리 | 외부 vLLM, 외부 lifecycle | native MLX-VLM, 외부 lifecycle |
| Chat / Responses, PII·Secret Risk | 제공 | 제공 | 제공 |
| Embedding / Retrieval / Prompt Injection detector | 제공 | 미제공 | 미제공 |
| Console 모델 전환 / Runtime 제어 / GPU admission | 제공 | 미제공 | 미제공 |
| monitoring stack | 제공 | 미제공 | 제공 |
| target qualification 선언 | verified | unverified | verified |

원본은 `configs/deployment_targets.yaml`이다. 이 표는 전체 하드웨어·모델 조합의 검증 보증이 아니다.
모델별 기능은 실제 `/v1/models`와 profile을 기준으로 설명한다. 현재 UI의 미지원 메뉴를 강제로
표시하거나 macOS 촬영에 Linux 모델 전환 장면을 이어 붙이지 않는다.

## 7. 공개 전 검수와 제작 진행

- [x] 정보 구조·핵심 문구·촬영 목록·스토리보드 작성
- [x] 최신 UI의 실제 주요 화면 확보 및 민감 정보 검수
- [x] [화면별 촬영 기록](../../assets/screenshots/showcase/README.md)과 실제 실행 범위 확인
- [x] README를 확보된 화면 기준으로 재구성
- [x] 이미지 분석·OCR·시스템 프롬프트·임베딩의 짧은 GIF와 정지 화면 확보
- [ ] 선택 사항: 90초 종합 데모 녹화·편집·자막·공개 링크 확보
- [ ] GitHub 실제 렌더링에서 이미지·상대 링크·영상 썸네일 확인
- [x] GitHub Markdown API 렌더 결과를 로컬 CSS로 1440 px / 390 px 확인: 이미지·alt·anchor 정상, 문서 전체 가로 넘침 없음
  (실제 GitHub 페이지의 최종 CSS 검수는 별도)

문구·링크 변경은 `git diff --check`, 로컬 링크 존재 검사와 `make validate`로 확인한다.
화면 확인과 실제 Runtime 검증은 구분해 기록한다. 영상이 아직 없으면 README에 영상 링크를
예고용 placeholder로 넣지 않고, 확보된 화면과 실제 사용 순서로 공개한다.
