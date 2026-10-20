# 가이드 목차

**외부 사용자는 서버 설치 명령 없이** 전달받은 접속 주소와 인증 정보로 이용합니다. 역할별로 필요한 가이드를 선택하세요.

| 작업 | 가이드 |
|---|---|
| 설치 및 첫 모델 응답 | [빠른 시작](getting-started.md) |
| 모델·Runtime·GPU 운영 및 복구 | [사용자 가이드](user-guide.md) |
| 외부 관리자의 브라우저 접속 | [Control Plane 접속](remote-access.md#external-admin) |
| 외부 팀원·앱의 HTTPS API 호출 | [외부 API 접속](api-integration.md#remote-api) |
| 서버 운영자의 Tailscale·Nginx·권한 구성 | [원격 접속 Host 구성](remote-access.md#operator-setup) |
| 애플리케이션 API·SDK 연동 | [API 연동 가이드](api-integration.md) |
| 저장소 코드 수정·테스트·기여 | [개발자 가이드](developer-guide.md) |

## 참고 자료

설정·API·모델 정책의 기준은 [기술 문서](../README.md)를 따릅니다.

화면별 촬영 환경과 검증 범위는 [가이드 화면 기록](../../assets/screenshots/guides/README.md), [Showcase 화면 기록](../../assets/screenshots/showcase/README.md)에 보존합니다. 화면에 표시되는 모델·GPU 상태와 수치는 사용 중인 환경에 따라 달라질 수 있습니다.

현재 기능 및 사용 방법은 [Control Plane UX](../reference/control_plane_operator_ux.md)와 [Playground 예제](../reference/control_plane_playground_examples.md)를 참고하세요.

- [자동 CPU/GPU Runtime 운영](adaptive-runtime.md): Core 기동, CPU 복구, GPU 복귀, 요청 보호와 중지 의도.
- [GPU Host 준비](gpu-host-preparation.md): GPU 식별, 24GB/48GB 정책 선택, UUID 할당과 향후 실장비 검증 절차.
