# ADR-0044: Risk capability와 model-backed Prompt detector 분리

- Status: Accepted
- Date: 2026-09-30
- Extends: [ADR-0020](./0020-runtime-control-and-deployment-targets.md), [ADR-0038](./0038-resource-aware-secondary-runtime-topology.md)

## Context

Risk Signal Service에는 서로 다른 실행 특성을 가진 detector가 함께 등록되어 있다.

- PII detector는 in-process Python 구현이다.
- Secret detector는 in-process Python 구현이다.
- Prompt Injection detector는 현재 별도 vLLM generation runtime을 사용한다.

기존 deployment feature `risk`는 이 셋을 하나로 묶었다. 따라서 static target은 Prompt
runtime을 제공하지 않는다는 이유로 GPU나 별도 model runtime이 필요 없는 PII/Secret까지
함께 제거했다. 이 차이는 OS 차이가 아니라 local application capability와 model-backed
runtime capability의 차이다.

ADR-0038은 이미 resource composition에 따라 Prompt runtime만 effective topology에서
제거해도 Risk feature 자체와 PII/Secret aggregate가 유지돼야 한다고 결정했다.

## Decision

Deployment capability를 다음처럼 분리한다.

- `risk`: Risk Signal Service와 local PII/Secret detector API를 제공한다.
- `prompt_detection`: model-backed Prompt Injection Detector runtime을 effective topology에 포함한다.

Prompt detector runtime의 topology binding은 `prompt_detection` feature에 연결한다.
`prompt_detection`은 `risk` 없이는 유효하지 않으며 target loader가 fail-closed한다.

Availability는 operating-system identity에서 추론하지 않는다.

- Linux NVIDIA dynamic은 `risk + prompt_detection`을 제공한다.
- Linux NVIDIA static과 macOS Metal static은 `risk`만 제공한다.
- static target은 공통 local-risk Compose overlay를 공유한다.
- 미래에 다른 backend의 Prompt detector가 추가되면 해당 target이 `prompt_detection`을
  활성화하고 runtime provider를 연결한다. macOS 여부 자체는 조건이 아니다.

Resource feasibility는 계속 ADR-0038의 effective topology가 소유한다. 따라서
`prompt_detection=true`인 target에서도 선택한 Main resource variant가 Prompt runtime과
공존할 수 없으면 해당 runtime만 unavailable이 된다.

Gateway readiness에서 Risk Signal Service는 `risk`가 켜진 동안 required dependency다.
Risk aggregate는 Prompt runtime lifecycle과 독립적으로 enabled detector만 실행한다.
Prompt 전용 endpoint는 detector가 effective-disabled면 기존 `DETECTOR_DISABLED` 계약을
유지한다.

## Consequences

- Static Linux/macOS target에서도 GPU 없이 PII/Secret Risk API를 제공한다.
- `/v1/models`에는 model-backed Prompt runtime이 실제 effective topology에 있을 때만
  `risk-prompt`가 나타난다.
- Main runtime backend와 detector availability를 결합하지 않는다.
- Static target에 Gateway -> Risk Signal Service 내부 호출 edge가 생기므로 internal
  service token과 service별 least-privilege env projection을 사용한다.
- macOS monitoring stack은 Risk Signal Service metric을 함께 수집한다.

## Non-goals

- Kanana Prompt model의 MLX 호환성 선언
- Prompt detector backend 자동 선택
- PII/Secret detector 구현 변경
- GPU resource constraint를 OS 또는 GPU product allowlist로 바꾸는 것
