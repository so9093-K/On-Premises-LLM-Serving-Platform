# Control Plane 운영자 작업 중심 UX

현재 Console은 **한국어 우선, deployment capability에 따른 접근 가능성, API/Runtime 소유권 보존**을 기준으로 구성한다.
이 문서는 [ADR-0027](../adr/0027-control-plane-runtime-configuration-and-console-boundary.md),
[ADR-0040](../adr/0040-control-plane-korean-capability-ux.md),
[ADR-0047](../adr/0047-control-plane-capability-aware-chat-playground.md)을 따르는 화면 사용 계약이다.
Navigation 메뉴와 실제 Route는 같은 feature-aware 정의를 사용하므로, 미지원 target에서 경로를 직접 입력해도 관리 화면이 열리지 않는다.
메뉴를 숨겼다고 Runtime/Model authority가 바뀌지는 않으며 권한 검증은 서버의 책임이다.

## 화면과 작업의 연결

| 사용자가 하고 싶은 일 | 시작점 | 확인할 결과 | 실제 authority |
| --- | --- | --- | --- |
| 현재 서비스 확인 | 운영 개요 | Main Model 및 Runtime의 조회 상태, 최근 Gateway 요청 집계 | Bootstrap / Runtime / Main Model / Traffic |
| 실제 모델 응답 검증 | 빠른 작업 → Playground | 공개 API 응답, request ID, 지연 및 요청 당시 설정 | `/v1/models` 및 `/v1/chat/completions` |
| 모델 변경 | 메인 모델 | 기능·자원 영향 검토 → 전환 진행 → 성공/복구/실패 | Main Model Control |
| 런타임 시작·중지 | 런타임과 GPU | 정책상 예약 및 변경 영향 Plan → Apply → Verification | Runtime Controller |
| 설정 편집·복원 | 설정 | Schema 그룹 → 현재 값·출처 → Plan/Apply 또는 Revision Restore | Configuration Plane |
| 장애·변경 이력 확인 | 운영 활동 | 작업 상태, 실패·복구 결과, Request/Operation ID 및 진단 링크 | Runtime / Main Model / Configuration |
| API 기능 탐색 | API 문서 | 지원 API, 공개 Request/Response Contract | Gateway / Scalar |

### 서비스 상태와 실제 모델 응답

- 개요의 "확인된 주의 항목 없음"은 **조회된 정보에서** 주의 항목을 찾지 못했다는 의미다. 추론 Canary 성공이나 무장애 보증이 아니다.
- 최근 서비스 지표는 Gateway 프로세스 내 API 요청 집계다. Process restart 뒤 초기화되며, GPU의 실측 값과 구분한다.
- 정책상 GPU 예약은 `gpu_budgets`와 활성 Runtime 설정을 이용한 Admission의 **추정·예약 비율**이다. DCGM이 관측한 VRAM 메모리 점유량이 아니다.
- `compatible`, `qualified`, `gate open`, `healthy`는 다른 상태이므로 하나의 정상 판정으로 결합하지 않는다.

### 모델 변경 결과

1. 현재 활성 프로필과 전환 후보를 비교한다.
2. 기능 감소, 리소스 정책, 검증 여부 및 중단 가능성을 확인한다.
3. 기존 Main Model mutation으로 전환을 요청한다.
4. 작업의 실제 단계와 완료/실패/복구 여부를 서버 결과로 표시한다.
5. 성공했을 때 Playground에서 **별도의 공개 API 요청**으로 새 응답을 확인할 수 있다.

### Runtime 작업

Runtime 목록은 설정된 실행 상태와 실제 관측 상태가 다를 수 있음을 유지한다.
Start/Stop은 직접 실행이 아니라 Plan/Apply 결과를 따르며, 다른 Runtime 자동 중지가 필요하면 별도 검토를 요구한다.
원시 Verification JSON, ID, Profile 및 Source identifier는 기술 상세에서 접근 가능해야 한다.

### Configuration 탐색

서버 Configuration Schema의 `group`과 `meaning`을 그대로 소비해 탐색한다. 현재 편집 가능한 그룹 `retrieval`, `streaming`의 사용자용 이름은 `uiText.ts`에만 둔다.
UI가 Key prefix로 별도 Category authority를 만들지 않는다. `owner`, `editable`, `control_surface`, `applicability`가 실제 편집 가능 여부를 결정한다.
기존 revision 검증, stale plan 거부 및 이전 상태 복원 계약은 그대로 유지한다.

### Playground

- 요청 본문은 공개 `/v1/models` 계약에서 허용하는 기능과 파라미터로만 구성한다.
- API Key, 관리자 Key, 대화는 탭 메모리 범위를 벗어나 영구 저장되지 않는다.
- 각 응답은 전송 당시 모델/Backend, Request ID 및 설정 정보를 유지한다.
- 작은 화면에서 요청 설정은 Chat 본문 뒤에 배치된다. 화면 상단의 바로가기와 입력창 복귀 링크로 이동한다.
- 스트리밍은 **대화 끝**을 기준으로 따라가며 모바일에서 대화 아래의 설정 패널 끝까지 스크롤하지 않는다. 사용자가 위로 스크롤해 읽는 중에는 자동 이동을 멈춘다.
- Scalar의 범용 API Reference나 Grafana의 로그 탐색 기능을 Console 안에 새로 복제하지 않는다.

## UX 검증 기준

- Dynamic target에서 model switching과 runtime control만 노출·실행하며, Static/external target은 외부 관리 이유를 알린다.
- 서비스가 정상으로 조회되더라도 추론 요청 성공을 보증하지 않는다.
- Plan과 Apply 사이 상태가 바뀌면 재검토하며, 실패 시 적용 성공으로 표시하지 않는다.
- 1440×900과 390×844 Chromium에서 Navigation, Chat + Tool result, 긴 응답, 설정과 Runtime 표를 확인한다.
- Mobile Chat에서 Streaming 중 수동 위쪽 스크롤을 방해하지 않고, settings 접근 및 입력창 복귀가 가능하다.
- Keyboard Tab/Enter/Focus handoff, screen reader 상태, 포커스 가시성, 색상 대비, Reduced Motion, 예외 상태를 검사한다.
- 관리자 자격 증명 전환 시 기존 in-memory Query cache를 제거해 이전 세션의 조회 결과를 재사용하지 않는다.
- 코드/계약 검증은 `make console-check`와 `make check`가 소유하며, 실제 GPU Runtime 품질을 이 UX 검증으로 대신하지 않는다.
