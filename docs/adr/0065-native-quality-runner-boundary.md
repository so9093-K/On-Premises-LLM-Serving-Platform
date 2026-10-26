# ADR-0065: 품질 실행은 Native Runner와 단일 CLI가 소유한다

## Status

Accepted

- Native Runner와 운영 Lifecycle의 경계는 유효하다. 기본 검사 범위와 CI 실행 조건은 현행 `Makefile`과 `.github/workflows/validate.yml`이 소유한다.
- ADR-0043의 one-off Runtime validation 실행 경로를 이 결정으로 대체한다. ADR-0043의 **raw Runtime host 미공개 및 내부 네트워크 격리 원칙**은 유지한다.
- ADR-0042의 Qualification 선언 정책과 별도 근거·성능 시스템을 두지 않는 결정은 유지한다.

## Context

Python, Console, Chromium 테스트와 정적 계약 검증이 여러 전용 Shell·Python 진입점에 나뉘었다. 검증 실행용 Compose와 CI script가 별도 Runner 계약을 갖게 되면 테스트 체계가 플랫폼 운영 기능에 종속된다. 변경이 필요한 것은 품질 실행 경계이지, 실제 배포·모델 Runtime의 동작이 아니다.

## Decision

1. 개별 테스트와 판정은 pytest, Vitest, Playwright Test의 Native Runner가 소유한다. 기존 테스트와 Fixture, 과거 검증 스크립트를 새 Runner로 이식하지 않는다.
2. `scripts/quality_cli.py`는 Suite 선택, 필요한 Runner 존재 확인, 명령 호출과 종료 상태만 소유한다. 일반 진입점은 `make test/validate/check/console-check/browser-test`다.
3. `make validate`는 Ruff 오류 및 canonical 생성 산출물 Drift를 확인한다. 삭제된 schema, shell, host-exposure, Runtime 전용 governance 전체를 검사한다고 주장하지 않는다.
4. `make up/status/logs/down`의 lifecycle, 배포 Preflight와 실제 Runtime Readiness는 플랫폼 운영 경계가 소유한다. 선택적 `make smoke`와 `make image-smoke`는 각각 대표 Gateway 호출과 이미지 HTTP 동작을 확인하며 전용 GPU/Runtime qualification 검증기는 제공하지 않는다.
5. GitHub Actions 등 CI는 동일한 저장소 진입점을 실행하는 Adapter다. JUnit XML은 명시적으로 요청한 경우에만 Native Runner가 기록한다. 실행 증거 DB, Qualification 승인·승격, Benchmark 기준선 시스템을 만들지 않는다.
6. 활성 문서는 실행 가능한 명령과 실제 보장 범위만 서술한다. 과거 검증 경로를 기술한 이전 ADR·측정 보고서는 작성 당시의 기록으로 보존한다.

## Consequences

| Positive | Negative |
|---|---|
| 운영 Lifecycle과 품질 Runner의 독립성을 유지한다 | 기존 전용 정적 governance가 보장하던 항목은 기본 품질 명령에서 더 이상 검사하지 않는다 |
| Suite 판정과 실행 오케스트레이션의 중복을 제거한다 | 이전의 전체 GPU/Runtime 전용 검증 명령을 사용할 수 없다 |
| Provider별 CI 구현을 줄인다 | 모델별 실제 장비 확인의 범위는 해당 운영 작업의 책임으로 남는다 |

## Operational impact

`make setup-dev`로 Python 개발 환경을 준비하고, UI 타입·빌드 도구는 `npm --prefix ui/control-plane ci`로 설치한다.
`make check`는 Ruff·생성 산출물 Drift·Control Plane 타입을 확인한다.
pytest·Vitest·Chromium·이미지 검사는 개별 명령으로 선택하며, UI 테스트 도구가 필요할 때 `make setup-test-runners`를 실행한다.
`make up` 성공 및 `make status`의 의미에는 변경이 없다.

## Related

- [ADR-0042](0042-remove-qualification-evidence-and-benchmark.md)
- [ADR-0043](0043-internal-runtime-validation-and-private-host-exposure.md)
- [테스트·검증 실행 체계](../08_testing_validation.md)
- [자동화 경계](../09_cicd.md)
