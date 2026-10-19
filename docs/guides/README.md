# 처음 사용하는 분을 위한 가이드

자체 인프라에서 플랫폼을 실행하고 첫 응답을 확인하려면 아래 순서로 진행하세요.
플랫폼 API를 이용하는 개발자와 이 저장소를 수정하는 개발자는 서로 다른 경로를 사용합니다.

| 하고 싶은 일 | 읽을 가이드 | 완료 기준 |
|---|---|---|
| 내 환경에 설치하고 첫 응답 받기 | [빠른 시작](getting-started.md) | 서비스 준비 확인 후 Playground 응답 수신 |
| 모델·GPU·설정을 운영하고 문제 해결 | [사용자 가이드](user-guide.md) | 상태 확인 → 영향 검토 → 실행 결과 → 별도 응답 검증 |
| 다른 지역에서 관리자·팀원 접근 분리 | [원격 접근 가이드](remote-access.md) | VPN Grants·API 제한 Proxy·실제 허용/차단 검증 |
| 내 서비스에서 API 호출하기 | [API 연동 가이드](api-integration.md) | 모델 조회, 일반·스트리밍 요청, SDK 또는 Playground 요청 재현 |
| 프로젝트 코드 수정·기여 | [개발자 가이드](developer-guide.md) | 개발 환경 준비, 변경에 맞는 검증, PR 작성 |

## 읽는 방법

각 작업은 **목표 → 사전 조건 → 실행 단계 → 화면 → 성공 기준 → 실패 시 조치**로 구성합니다.
설정·프로토콜·모델 정책의 상세 계약은 [기술 문서 목차](../README.md)로 연결합니다.
가이드는 작업 순서를 안내하며 설정 파일의 값이나 API 스키마를 대신하지 않습니다.

## 화면과 실행 범위

[단계별 새 화면과 촬영 조건](../../assets/screenshots/guides/README.md)은 2026-10-19 Linux/NVIDIA에서
재기동·인증·Playground·API/SDK·요청 내보내기를 확인한 기록입니다.
스트림 중단은 브라우저에 테스트 응답을 주입한 경우로 따로 표시합니다.
Mac과 외부 Runtime의 안내는 설정·구현을 대조한 범위이며 이번 장비에서 실행한 기록이 아닙니다.

[기존 화면](../../assets/screenshots/showcase/README.md)은 2026-10-15의 실제 Linux/NVIDIA
운영·추론 기록입니다. 최신 UI의 Playground 예제 갤러리, 오디오 예제,
**코드로 사용하기**가 추가되기 전 화면이므로 버튼 위치가 현재와 다를 수 있습니다.
화면마다 의미를 설명하고, [최신 운영 UX](../reference/control_plane_operator_ux.md)와
[Playground 예제](../reference/control_plane_playground_examples.md)를 함께 안내합니다.

모델 전환 영향 화면은 전환 성공 기록이 아닙니다. GIF의 주문서·그래프는 공개용 예시 입력이며,
응답·운영값은 각각 [기능 데모의 촬영 조건](../reference/feature_demos.md)을 따릅니다.
Target의 `verified` 선언은 모든 장비·모델 조합의 동작 보증이 아닙니다.
