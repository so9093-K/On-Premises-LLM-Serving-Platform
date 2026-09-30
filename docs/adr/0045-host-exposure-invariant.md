# ADR-0045: Host exposure는 selectable mode가 아니라 deployment invariant다

## Status

Accepted

- Extends: [ADR-0025](./0025-user-access-profiles-and-legacy-migration.md)
- Refines: [ADR-0043](./0043-internal-runtime-validation-and-private-host-exposure.md)

## Context

ADR-0043에서 `master_open`과 diagnostic exposure override를 제거한 뒤 지원 host topology는
하나만 남았다. Gateway와 target이 제공하는 Grafana만 host에 publish하고 model runtime,
Risk Signal Service, Prometheus/exporter/log backend는 Compose 내부망에 둔다.

그럼에도 repository에는 다음 상태가 남아 있었다.

- `EXPOSURE_MODE=private_network`
- 단일 entry만 가진 `configs/exposure_profiles.yaml`
- Deployment Target의 `exposure_profile_applies`
- Access/Auth/Control Plane/preflight의 exposure-mode projection과 comparison

선택 가능한 값이 하나뿐인 상태를 mode/profile로 유지하면 host publication의 실제 authority인
service role과 Compose `ports`에서 벗어난 별도 state가 생긴다.

한편 `EXPOSURE_AUDIENCE`는 같은 종류의 값이 아니다. `local_only`, `private_lan`은
Access Profile의 network intent와 loopback/LAN bind safety를 설명하며 legacy/custom 구성의
fail-closed 진단에도 실제로 사용된다.

## Decision

1. Host exposure를 selectable mode가 아닌 deployment invariant로 취급한다.
2. Host-published service role은 `configs/services.yaml`이 소유한다.
   - `public_entrypoint`은 host-published 대상이다.
   - target이 monitoring stack을 실행하면 `visualization`도 host-published 대상이다.
3. Target Compose의 실제 `ports` 집합은 위 service-role projection과 `make validate`에서
   직접 대조한다.
4. `configs/exposure_profiles.yaml`, `EXPOSURE_MODE`,
   `DeploymentTarget.exposure_profile_applies`를 active configuration에서 제거한다.
5. Access Profile은 auth mode, `EXPOSURE_AUDIENCE`, host bind policy와 external TLS owner만
   소유한다. Access Profile이 host-published service 종류를 바꾸지는 않는다.
6. 기존 env의 retired `EXPOSURE_MODE`는 migration input으로만 읽는다.
   - `private_network` marker는 configuration sync에서 제거한다.
   - `master_open` 등 non-private 값은 자동 재해석하지 않고 explicit
     `ACCESS=local|private|edge CONFIRM=access` migration을 요구한다.
7. `EXPOSURE_AUDIENCE`는 현재 safety boundary이므로 유지한다.

## Consequences

- host publication의 Source of Truth가 service registry와 actual Compose로 수렴한다.
- Access Profile은 사용자 접근 의도만 표현하며 infrastructure topology selector 역할을 하지 않는다.
- 새로운 host-published service를 추가하려면 service role과 target Compose port를 같은 변경에서
  수정해야 하고 validator가 drift를 거부한다.
- old `EXPOSURE_MODE`를 쓰는 deployment는 한 번의 explicit migration이 필요하다.
- legacy/custom 지원을 향후 종료하면 `EXPOSURE_AUDIENCE`의 persistent projection도 별도로
  재평가할 수 있지만 이 ADR에서는 제거하지 않는다.

## Related

- [ADR-0025](./0025-user-access-profiles-and-legacy-migration.md)
- [ADR-0043](./0043-internal-runtime-validation-and-private-host-exposure.md)
- [4. 실행 환경과 모드](../04_runtime_modes.md)
- [5. 설정 체계와 Source of Truth](../05_configuration.md)
