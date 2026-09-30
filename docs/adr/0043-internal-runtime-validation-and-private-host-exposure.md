# ADR-0043: Runtime qualification을 Compose 내부망에서 실행하고 host exposure를 private topology로 고정한다

## Status

Accepted

- Partially supersedes: [ADR-0025](./0025-user-access-profiles-and-legacy-migration.md)의
  `master_open` 유지와 `exposure-*` Advanced/legacy 호환 결정

## Context

Full-stack runtime validation은 원래 host Python process에서 실행됐다. Main/Embedding/Prompt
vLLM, Risk Signal Service, Prometheus 같은 내부 endpoint를 검사하려면 이 서비스들의 port를
host에 publish해야 했고, 그 목적 때문에 일반 Access Profile이 사용하지 않는
`master_open` exposure mode와 generated Compose override, plan/apply/status 도구를 유지했다.

PR #185 시점에는 runtime validation과 performance benchmark가 이 경로의 실제 consumer였다.
이후 benchmark 체계가 제거되면서 qualification 하나를 위해 raw model/runtime/operations
endpoint를 host에 여는 별도 topology를 유지하는 비용이 남았다.

Platform image는 application runtime artifact이며 validation script를 포함하지 않는다는
기존 경계도 유지해야 한다. Validator가 Gateway container 안에 들어가거나 production image가
개발/검증 source를 품는 방식은 이 경계를 역전시킨다.

## Decision

1. Canonical `make runtime-validate`는 실행 중인 Compose project network에 one-off
   `runtime-validator` container로 참여한다.
2. 내부 endpoint는 `configs/services.yaml`의 `compose_service + container_port`에서
   파생한다. Qualification 때문에 host port를 추가로 publish하지 않는다.
3. Validator는 `docker compose run --rm --no-deps` 의미론을 사용한다. 필요한 dependency가
   내려가 있으면 실패하며 시작·재시작·복구하지 않는다.
4. Production Platform image 구성은 바꾸지 않는다. Validator는 같은 image의 Python/runtime
   dependency를 사용하되 repository의 `src/`, `scripts/`, `configs/` 등을 read-only로
   mount하고 report directory만 쓴다.
5. Full-stack host exposure topology는 `private_network` 하나로 고정한다. Gateway와 Grafana만
   host에 publish하고 model runtime, Risk Signal Service, Prometheus, exporter, Loki는
   Compose 내부망에 둔다.
6. `master_open`, generated exposure override, `exposure-plan/apply/status` surface를 제거한다.
7. 기존 `EXPOSURE_MODE=master_open` env는 `private_network`로 자동 재해석하지 않는다.
   운영자가 `ACCESS=local|private|edge`를 명시해 plan을 확인한 뒤 migration한다.
8. 특정 원격 후보 endpoint를 좁혀 검사하는 CLI/process URL override는 maintainer 호환 경로로
   남길 수 있지만, full-stack qualification의 canonical 경로는 내부망 `make runtime-validate`다.

## Consequences

| Positive | Negative |
|---|---|
| 검증을 위해 raw runtime/operations port를 host에 열지 않는다 | Validator용 one-off Compose 정의와 mount 경계를 유지해야 한다 |
| public request boundary가 Gateway로 단순해진다 | 실제 NVIDIA host qualification은 일반 GitHub-hosted CI가 대신할 수 없다 |
| diagnostic exposure override와 관련 validation/plan/apply 코드가 사라진다 | 기존 master_open 환경은 한 번 명시적 Access migration이 필요하다 |
| service endpoint authority가 host port 복제 대신 service registry로 수렴한다 | 원격 후보 검증은 endpoint override를 명시해야 한다 |
| dependency가 내려간 상태를 validator가 고쳐 숨기지 않는다 | qualification 전에 stack이 이미 실행 중이어야 한다 |

## Operational impact

```bash
make up TARGET=linux-nvidia-dynamic ACCESS=local
make runtime-validate
```

`make runtime-validate` 전후에 internal service의 host-published port 집합은 변하지 않는다.
Validator 종료 후 one-off container는 제거된다. 검증 report는 기존처럼
`reports/runtime/`에 JSON/Markdown으로 남는다.

기존 환경에 `EXPOSURE_MODE=master_open`이 남아 있으면 `make up`은 fail-closed한다.

```bash
make up ACCESS=private
make up ACCESS=private CONFIRM=access
```

첫 명령은 plan을 보여 주고 두 번째 명령이 지원 Access Profile을 원자적으로 적용한다.

## Related

- [ADR-0025](./0025-user-access-profiles-and-legacy-migration.md)
- [ADR-0037](./0037-local-lifecycle-deployment-authority.md)
- [4. 실행 환경과 모드](../04_runtime_modes.md)
- [8. 테스트와 검증](../08_testing_validation.md)
