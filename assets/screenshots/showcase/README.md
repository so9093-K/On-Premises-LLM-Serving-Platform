# Control Plane 화면 촬영 정보

촬영일: 2026-10-15 · 실제 모델 응답 및 운영 상태 · 시뮬레이션 수치 없음

## 촬영 환경

- UI / Gateway source: `25462454` (PR #224 반영), served bundle `index-JT9ch5SF.js`.
- 촬영용 platform image: `sha256:360bab523ca5ea8b5a592c76b264c3859217c5eba9f1359307910b9c0e91ec39`.
- 최신 Gateway를 별도 실행하고, 기존 managed stack의 Runtime Controller·Risk service·Main Runtime에 연결했다.
  연결한 Controller/Risk의 platform source는 `1b6cea4a`다. 전체 stack을 새 버전으로 재배포한 검증은 아니다.
- target: `linux-nvidia-dynamic`, Main profile: `gemma4-e4b-it`, resource variant: `rtx4090-24gb`.
- model: `google/gemma-4-E4B-it`, revision `ee0ef6023621cff504d758262d4e04895a5af4a2` (실행 중인 Runtime argv 확인).
- Chromium, viewport 1440×900, device scale 1, zoom 100%, dark theme, `ko-KR`, `Asia/Seoul`.
- Gateway의 요청 집계·설정 저장소는 촬영용으로 분리했다. 기존 운영 Gateway 설정을 변경하지 않았다.
- PNG viewport capture. 픽셀·문구·상태·응답·지연을 수정하거나 가리지 않았다.
  browser chrome와 인증 입력 화면은 포함하지 않았다. API Key·내부 IP·민감 로그가 없는지 이미지별로 검수했다.

## 화면과 실제 수행 범위

| 자산 | 실제 관찰·수행 | 해석 경계 |
|---|---|---|
| [운영 개요](overview.png) | 실제 요청 후 상태와 프로세스 내 최근 집계 조회 | 작은 표본에서 p95가 표시되지 않을 수 있다. 정상 추론 보증이 아니다 |
| [Playground](playground.png) | 아래 질문으로 실제 streaming Chat 요청, 최대 출력 토큰 256 | 한 요청의 응답과 지연이며 성능 benchmark가 아니다 |
| [메인 모델](main-model.png) | 현재 E4B와 profile catalog 조회 | 후보가 표시되는 것과 현재 host에서 전환을 검증한 것은 다르다 |
| [전환 영향 검토](model-review.png) | 12B 후보의 검토 화면 열기 | 전환 요청은 실행하지 않았다. 전환 성공·rollback 실측이 아니다 |
| [런타임과 GPU](runtimes.png) | 현재 관측 상태와 예약 정책 조회 | 원하는 상태와 실제 상태가 다를 수 있다. GPU 비율은 실측 VRAM이 아니다 |
| [설정](configuration.png) | 촬영용 Gateway의 실제 설정·출처 조회 | `streaming.max_duration_seconds`를 300→240으로 변경한 상태 |
| [운영 활동](operations.png) | 위 설정 변경의 Plan→Apply→Verify 기록 | 실제 설정 변경 1건이며 모델 전환 기록이나 일반 추론 로그가 아니다 |

공개용 입력:

> 사내 AI 모델 API를 운영할 때 확인할 사항 세 가지를 한 문장씩 한국어로 알려주세요.

입력은 촬영용 예시이며 응답은 실제 모델 출력이다. 공개 API 요청으로 생긴 request ID만 화면에 포함한다.
설정 변경은 촬영용 Gateway에만 적용했으며 해당 인스턴스와 임시 저장소는 촬영 종료 후 정리했다.

