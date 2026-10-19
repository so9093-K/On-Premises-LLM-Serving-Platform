# 기술 문서

프로젝트의 구조·설정·API·운영 계약을 확인하는 문서 목차입니다. 처음 실행하거나 Console을 사용하려면 가이드부터 시작하세요.

## 가이드

| 작업 | 문서 |
|---|---|
| 설치와 첫 모델 응답 | [빠른 시작](guides/getting-started.md) |
| Control Plane 운영·복구 | [사용자 가이드](guides/user-guide.md) |
| 개인·팀 VPN 접속 | [원격 접속](guides/remote-access.md) |
| 애플리케이션 API 연동 | [API 연동](guides/api-integration.md) |
| 코드 수정·검증·기여 | [개발자 가이드](guides/developer-guide.md) |

## 플랫폼·요청 계약

| 주제 | 문서 |
|---|---|
| 플랫폼 소개 | [프로젝트 개요](01_overview.md) |
| 요청 처리 | [요청 흐름](02_request_flow.md) |
| 서비스 경계 | [시스템 구성](03_system_components.md) |
| 환경과 실행 방식 | [실행 환경](04_runtime_modes.md) |
| 설정·정책의 소유권 | [설정 Source of Truth](05_configuration.md) |
| 모델 전환·GPU 정책 | [모델 운영](06_model_operations.md) |

## 개발·배포·운영

| 주제 | 문서 |
|---|---|
| 로컬 개발·빌드 | [개발 환경](07_local_dev_build.md) |
| 테스트 범위·검증 | [테스트와 검증](08_testing_validation.md) |
| 수동 성능 측정·Mac 실측 | [AIPerf 절차](../ops/perf/README.md) · [측정 기록](resources/macos_aiperf_measurement.md) |
| 자동화 책임 | [CI 경계](09_cicd.md) |
| 배포 방식 | [배포](10_deployment.md) |
| 지표·로그·Grafana | [관측성](11_observability.md) |
| 장애·복구 | [운영 관리](12_operations.md) |
| 변경별 소유권·영향 | [변경 가이드](13_change_guide.md) |

## 참고 자료

[API Reference](reference/api_reference.md) · [OpenAI 호환성](reference/openai_compatibility.md) · [표준 용어](reference/terminology.md) · [API 문서 화면](reference/api_docs_reference.md)

[Control Plane UX](reference/control_plane_operator_ux.md) · [Playground 요청 재현](reference/playground_integration.md) · [기능 데모](reference/feature_demos.md)

[vLLM 보안 노출 경계](reference/vllm_security_posture.md) · [vLLM 실행 경계](reference/vllm_execution_boundary.md) · [부록](appendix.md)

## 문서 관리

현재 설정·API의 실제 소유권은 [설정](05_configuration.md)과 [변경 가이드](13_change_guide.md)를 따릅니다. 문서는 정책을 중복 정의하지 않으며, 아키텍처 결정은 [ADR](adr/README.md), 기여 원칙은 [CONTRIBUTING](../CONTRIBUTING.md)이 소유합니다.
