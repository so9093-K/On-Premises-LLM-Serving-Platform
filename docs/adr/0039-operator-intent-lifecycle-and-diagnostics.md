# ADR-0039: Operator lifecycle is intent-based

## Status

Accepted

## Context

로컬 lifecycle은 target 차이를 하나의 orchestration에 모았지만 공개 사용 흐름 자체는
`setup → build → prepare → up/status/down`으로 남아 있었다. 이 흐름은 내부 구현 단계와
사용자의 의도를 같은 수준에 노출한다.

그 결과 정상 기동을 위해 사용자가 환경 생성, image build, model cache 준비, Compose
기동, readiness와 smoke의 관계를 알아야 했다. 장애 대응도 `ready-full`,
`compose-diagnostics`, `compose-logs` 같은 implementation entrypoint를 추가로 기억해야
했고, 진단 가능성을 높이기 위해 raw service log를 기본 터미널에 대량 출력하는 방향으로
복잡도가 증가했다.

초기화와 삭제도 `clean`, `reset`, `down-all`의 범위가 이름만으로 구별되지 않았다.
특히 model cache와 project-built image는 재생성 비용이 크므로 단순 상태 초기화와
artifact 폐기를 같은 명령에 두면 안 된다.

## Decision

### 1. Operator command surface는 intent를 기준으로 제한한다

정상 운영자가 기억해야 하는 repository-owned command는 다음 여섯 개다.

| Intent | Command | Contract |
|---|---|---|
| 사용 가능한 상태로 수렴 | `make up` | 최초 bootstrap, 필요한 build/cache 준비와 시작을 수렴하고 target-appropriate serving gate를 내부적으로 수행 |
| 현재 상태 확인 | `make status` | health/runtime policy를 요약하고 주의할 항목과 다음 행동을 표시 |
| 실행 리소스 정지 | `make down` | 이 checkout이 소유한 process/container/network를 정지하고 재사용 artifact는 보존 |
| 운영 로그 확인 | `make logs` | 기본은 error/readiness structured event, 필요할 때 all/raw/service/follow로 확장 |
| 로컬 상태 초기화 | `make reset` | configuration/runtime state를 제거하고 비싼 image/model cache는 보존 |
| project-owned artifact 폐기 | `make purge` | 확인된 scope에서 project image/model cache/volume까지 제거하고 host-global cache는 보존 |

첫 실행만 target 선택이 필요하다.

```bash
make up TARGET=<deployment-target> [ACCESS=local|private|edge]
```

이후 정상 시작은 `make up` 하나다.

### 2. `up`은 순서형 bootstrap이 아니라 desired-state convergence다

`make up`은 필요한 단계를 내부적으로 판단한다.

- runtime Python environment가 없거나 lock과 다르면 동기화한다.
- persistent `.env`가 없으면 target/access 입력으로 생성하고, 있으면 비파괴 sync한다.
- external registry digest는 그대로 보존한다.
- local project image가 현재 clean source와 일치하면 재사용한다.
- local image가 없거나 stale하면 Docker cache를 사용해 필요한 artifact를 다시 만든다.
- pinned Main Model snapshot은 local cache를 먼저 확인하고 없을 때만 다운로드한다.
- target별 runtime을 시작하고 serving gate를 검증한다. managed dynamic은 strict readiness와 representative inference path까지, static target은 외부 Main dependency를 포함한 Gateway readiness까지 확인한다.

이 단계들의 script는 구현 계층으로 남을 수 있지만 동명의 public Make alias를 두지 않는다.

### 3. `down`이 checkout ownership 기반 recovery도 소유한다

정상 target state가 있으면 해당 target을 정지한다. `.env`가 없거나 일부 상태가 손상된
경우에도 checkout ownership label/PID를 사용해 남은 실행 리소스를 정리한다.

별도 `down-all` operator command를 두지 않는다.

### 4. Reset과 purge의 파괴 범위를 분리한다

`reset`은 다시 설정할 수 있는 local state 초기화다.

- 제거: `.env`, `.venv`, `.runtime`, process logs/run files, build/test artifact
- 보존: project-built image, repository-local model cache, Docker volume, global Hugging Face
  cache, daemon-wide BuildKit cache, unrelated Docker resources

`purge`는 비싼 재사용 artifact를 버리는 명시적 destructive operation이다.

- `SCOPE=cache`: project-owned image, repository-local model cache, project Compose volume,
  build/test/log diagnostic artifact를 제거하고 configuration state는 보존
- `SCOPE=all`: cache scope에 더해 reset-owned local state도 제거
- 두 scope 모두 global Hugging Face cache, daemon-wide BuildKit cache와 unrelated Docker
  resource를 제거하지 않는다.

둘 다 plan-first이며 정확한 confirmation 없이는 삭제하지 않는다.

### 5. Operator output과 diagnostic evidence를 분리한다

진단 가능성을 raw terminal volume과 동일시하지 않는다.

- 정상 command output은 단계, 결과, policy state와 다음 행동을 짧게 표시한다.
- structured application event는 request ID, route, status, latency, error/diagnostic code 같은
  검색 가능한 필드를 유지한다.
- 실패한 내부 단계의 전체 stdout/stderr는 `.runtime/operator-logs/`에 evidence로 보존하고
  터미널에는 마지막 관련 근거와 파일 위치를 표시한다.
- Compose failure diagnostics는 service별 raw log를
  `.runtime/diagnostics/<id>/`에 보존하고 기본 터미널에는 분류된 원인과 비정상 service만
  표시한다.
- `PLATFORM_VERBOSE=1` 또는 `make logs RAW=1`은 명시적 deep-diagnostic 경로다.

### 6. Removed Make aliases는 compatibility surface로 남기지 않는다

다음 명령은 public Make target에서 제거한다.

`setup`, `build`, `rebuild`, `prepare`, `down-all`, `compose-up`,
`compose-config`, `ready-local`, `ready-full`, `smoke`, `compose-down`,
`compose-restart`, `compose-logs`, `compose-diagnostics`, `clean`, `help-all`,
`init-env-compose`, `sync-env`, `static-compose-config`.

CI, qualification, release와 maintainer 작업에 필요한 기능 자체는 해당 script 또는
developer-specific target에 남길 수 있다. 구현 script의 존재는 operator command를
자동으로 의미하지 않는다.

## Consequences

| Positive | Negative |
|---|---|
| 정상 기동과 재기동의 mental model이 `make up` 하나로 수렴한다. | `up` orchestration이 더 많은 convergence 책임을 가진다. |
| 내부 lifecycle 단계 추가가 operator command 증가로 이어지지 않는다. | 과거 세부 Make alias를 직접 사용하던 로컬 습관은 변경해야 한다. |
| reset과 artifact 폐기의 비용·위험 경계가 명확해진다. | purge는 ownership을 증명할 수 없으면 fail-closed해야 한다. |
| raw evidence를 보존하면서 terminal noise를 줄일 수 있다. | operator summary/classification 품질을 지속적으로 관리해야 한다. |
| status/logs가 backend 종류와 무관한 안정 UX가 된다. | maintainer는 필요할 때 implementation script를 직접 사용한다. |

## Operational impact

일반 운영 문서와 README는 여섯 command만 정상 lifecycle로 안내한다. 테스트/qualification
문서는 내부 script를 언급할 수 있지만 이를 정상 operator workflow로 제시하지 않는다.

과거 명령을 찾지 못했을 때 새 alias를 다시 추가하는 대신 현재 intent에 맞는 canonical
command 또는 implementation script를 선택한다.

## Migration notes

- 첫 설치 문서는 `setup/build/prepare/up`에서 `up TARGET=...`으로 변경한다.
- full-stack env 생성·migration과 static Compose projection은 `make up`이 정상 lifecycle에서 소유하며, 분리 진단이 필요한 maintainer만 implementation script를 직접 사용한다.
- 기존 `down-all` 사용 목적은 `down`이 흡수한다.
- `clean`의 저비용 repository maintenance 기능은 script implementation으로만 남는다.
- 기존 `reset`에서 image/model cache 삭제 책임을 제거하고 해당 책임을 `purge`로 이동한다.
- readiness/smoke/Compose diagnostic script는 `up` 내부 검증 또는 maintainer direct script로
  사용한다.
- legacy command alias를 deprecation shim으로 유지하지 않는다. 현재 version이 0.x인 동안
  public surface를 명확하게 정리하는 비용이 장기적인 compatibility debt보다 작다.

## Related

- [ADR-0013](0013-env-lifecycle-non-destructive-sync.md)
- [ADR-0022](0022-application-request-event-ownership.md)
- [ADR-0023](0023-local-lifecycle-command-boundaries.md) — superseded
- [ADR-0024](0024-public-errors-and-operational-diagnostics.md)
- [ADR-0037](0037-local-lifecycle-deployment-authority.md)
