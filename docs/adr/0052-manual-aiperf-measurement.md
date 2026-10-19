# ADR-0052: 수동 성능 측정은 외부 AIPerf와 장비별 실측 기록이 소유한다

## Status

Accepted

- Partially supersedes: [ADR-0042](0042-remove-qualification-evidence-and-benchmark.md)의
  Decision 5 중 수동 성능 측정 도구까지 제거한 범위.

## Context

Gateway·MLX/vLLM의 요청 지연과 Queue를 실제 장비에서 비교하려면 재현 가능한
Workload와 Client 측정값이 필요하다. 운영 Dashboard의 최근 트래픽은 입력 길이·부하·
Reasoning이 다른 요청을 섞으므로 통제한 실험을 대신하지 않는다.

ADR-0042는 사용되지 않는 Benchmark 계약·Baseline 승격·성능 Gate를 제거했다.
PR #244는 소비자가 없는 공통 Runner와 합성 Result Manifest를 제거하고 각 도구의
종료 코드·원본 결과를 성공·실패의 근거로 유지한다. 측정 요구가 이 체계의 부활을
정당화하지는 않는다.

## Decision

1. AIPerf 0.13.0을 별도의 `ops/perf` Python project와 lock으로 설치한다.
   Platform·MLX 설치와 일반 CI는 이 의존성을 소비하지 않는다.
2. 공통 Streaming Chat Workload는 AIPerf 자체 YAML Schema와 CLI를 사용한다.
   Short Chat, Long Prompt, Concurrent Chat의 입력 목표·출력 상한을 정의하고,
   실제 서버 usage와 분포를 원본 결과로 보존한다.
3. 정상 부하와 Admission 한도를 넘는 Queue 실험을 구분한다. Mac의 동시성 2는
   현재 한도 1을 넘는 Backpressure 관측이며 동시 실행 지원의 선언이 아니다.
4. Client TTFT·TTFO·ITL 추정값·E2E·Throughput과 Runtime 측정값은 별개다.
   MTP Chunk와 per-chunk usage의 한계, Native 최근 요청 Peak Memory의 의미를
   측정 기록에 명시한다.
5. 결과는 AIPerf 고유 JSON/CSV/JSONL과 로그를 그대로 사용하며 `reports/perf/`를
   Git에서 제외한다. 자체 Runner·Parser·Result Schema·Baseline·Promotion·SLO·
   Release Gate를 두지 않는다. 도구 실패와 유효한 측정의 성능 차이는 별도 상태다.
6. 공유하는 기록에는 장비·실행 계약·도구/소스 버전·Warmup·Cache·Reasoning·실제
   토큰 수와 확인한 숫자만 선별한다. 원본 Prompt·응답·키는 Git에 넣지 않는다.
7. OS별 설치·Gateway 호환성과 실제 Workload 실행은 해당 장비에서 확인한다.
   Mac 실측은 Ubuntu/NVIDIA 지원 완료를 의미하지 않는다. Linux lock 해석 역시
   NVIDIA 설치·Runtime·성능 검증을 대신하지 않는다.
8. 모델/GPU·Runtime·입출력·전원·부하 등 비교 조건이 다르면 직접적인 회귀 판정을
   하지 않는다. Qualification 선언은 기존 Runtime 기능 검증과 Maintainer 책임을 유지한다.

## Consequences

- 개발자가 동일 CLI와 고정 의존성으로 수동 측정을 반복할 수 있다.
- 성능 실측을 일반 CI와 분리하며, 외부 도구의 설정·지표 의미를 다시 구현하지 않는다.
- 독립된 외부 도구 lock을 유지하고 도구 버전 변경 시 실제 호환성을 다시 확인해야 한다.
- 비교 가능성·Sample 적합성·수치 해석은 실행자와 Reviewer가 판단한다.

## Operational impact

`make up/check/runtime-validate`의 계약은 유지한다. 준비된 Gateway에 명시적으로
AIPerf를 실행하며, 부하 실험 중 응답 지연과 Queue가 증가할 수 있다.
별도 가상환경·결과 경로만 추가하고 모델·GPU 정책이나 Image를 변경하지 않는다.

## Related

- [수동 측정 절차](../../ops/perf/README.md)
- [macOS 실측 기록](../resources/macos_aiperf_measurement.md)
- [테스트와 검증](../08_testing_validation.md)
- ADR-0039, ADR-0042, ADR-0050
