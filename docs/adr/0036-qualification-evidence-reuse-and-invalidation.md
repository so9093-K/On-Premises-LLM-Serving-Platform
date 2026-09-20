# ADR-0036: Qualification evidence reuse and invalidation

- Status: Accepted
- Date: 2026-09-20
- Refines: [ADR-0032](./0032-qualification-evidence-v1.md), [ADR-0033](./0033-qualification-status-promotion-contract.md), [ADR-0035](./0035-capability-based-hardware-admission-and-transparent-operations.md)

## Context

Qualification evidence v1은 각 `qualified_run`에 runtime image, engine/version, GPU, driver,
resource policy와 검증 시각을 정직하게 기록한다. 그러나 모든 fingerprint field를
profile-level `qualification.status`의 identity로 사용하면 새 GPU, driver 변경, host 교체,
resource-policy override만으로 같은 Main Model contract를 매번 다시 qualification해야 한다.

반대로 fingerprint를 전혀 고려하지 않으면 과거 run과 현재 contract의 의미가 달라졌을 때도
`verified`를 계속 주장할 수 있다. 특히 qualification check registry가 확장될 때 과거 immutable
receipt를 새 check 결과로 다시 써서 맞추는 것은 evidence 자체를 오염시킨다.

따라서 **run provenance**와 **현재 profile qualification eligibility**의 identity를 분리한다.

## Decision

### 1. Profile-level current qualification은 contract identity로 매칭한다

현재 `configs/main_model_profiles.yaml`의 `qualification.status=verified`를 뒷받침하는
evidence는 다음 contract identity가 일치해야 한다.

- `profile_id`
- `model_id`
- immutable `revision`
- `deployed_input` capability 집합
- Main Model profile catalog를 사용하는 현재 deployment target
- `qualified_run`이면 현재 capability별 required qualification check를 모두 `passed`

이 집합이 profile-level current evidence의 match key다.

### 2. Runtime/hardware fingerprint는 run provenance이며 profile match key가 아니다

다음 값은 실제 run이 어디에서 어떤 실행 artifact로 수행됐는지를 설명하는 provenance다.

- runtime engine / version
- runtime image distribution digest
- GPU product name
- GPU UUID와 memory observation
- driver version
- `resource_variant`
- `validated_at`

이 값이 다르다는 이유만으로 같은 profile contract의 `qualification.status`를 자동 강등하거나
새 GPU 사용을 막지 않는다.

새 GPU, GPU UUID 교체, driver 변경, reboot/redeploy, 같은 deployment target 안의
reference policy와 reviewed resource override 차이, evidence의 나이 자체는
profile-level 재qualification trigger가 아니다.

현재 host에서 실제로 실행 가능한지는 ADR-0035의 deployment/runtime compatibility,
resource admission/feasibility, start/apply 뒤 runtime validation이 판단한다.

### 3. Contract identity가 바뀌면 과거 evidence는 history로만 남는다

다음 변화는 기존 record를 삭제하거나 수정하지 않지만 현재 profile의 positive evidence로는
재사용하지 않는다.

- model ID 변경
- immutable revision 변경
- deployed capability 집합 변경
- evidence target이 더 이상 Main Model profile catalog를 소유하지 않음
- 현재 capability contract가 요구하는 required qualification check가 기존 `qualified_run`에 없음

새 current contract를 `verified`로 유지하거나 승격하려면 현재 contract를 만족하는 evidence가
필요하다.

### 4. Qualification check contract의 확장은 과거 receipt를 재작성하지 않는다

`configs/qualification_checks.yaml`에 새 required check가 추가되어도 기존
`qualified_run` receipt의 recorded check set은 그 실행 당시의 사실로 보존한다.

과거 run에 새 check 결과를 추정하거나 추가하지 않는다. Repository validation은 과거 receipt의
구조와 recorded result를 계속 인정하되, 그 run이 **현재** required check 집합을 충족하지 않으면
current verified evidence 또는 신규 status promotion 근거로 사용하지 않는다.

Stable check ID는 historical receipt를 계속 해석할 수 있도록 append-compatible하게 관리한다.

### 5. Runtime artifact 변경은 별도 release confidence 문제다

새 runtime image digest나 engine/version은 해당 artifact의 새로운 run provenance를 만들 이유가
될 수 있다. 다만 현재 profile-level qualification status가 runtime artifact digest를 identity로
소유하지 않는 이상 image/engine 변경만으로 hardware support나 profile qualification을 자동
무효화하지 않는다.

특정 immutable image 또는 engine version 자체를 release certification authority로 만들 필요가
생기면 기존 profile-level status에 암묵적으로 섞지 않고 별도 contract/axis로 정의한다.

현재 배포 artifact의 안전성은 runtime validation과 release/deploy 검증이 계속 소유한다.

### 6. Evidence에는 암묵적 만료 시간을 두지 않는다

`validated_at`은 provenance다. 별도 expiry policy가 Source of Truth로 도입되기 전까지
시간 경과만으로 evidence를 stale 처리하지 않는다.

## Consequences

- RTX A6000, RTX 6000 Ada, RTX 4090 또는 미래 GPU라는 제품명 자체가 재qualification 요구가 되지 않는다.
- Hardware/driver/resource policy fingerprint는 계속 완전하게 기록하지만 support allowlist로 승격되지 않는다.
- Qualification check가 강화되어도 immutable historical receipt를 다시 쓰지 않는다.
- Current verified status와 신규 promotion은 현재 required check contract를 만족하는 evidence만 사용한다.
- Runtime artifact-specific certification이 필요해질 경우 별도 authority를 추가해야 하며 기존 profile status의 의미를 몰래 확장하지 않는다.

## Non-goals

- Hardware compatibility 또는 VRAM feasibility를 qualification evidence에서 추론
- GPU product별 support matrix 생성
- Evidence receipt 수정 또는 backfill로 새 check 결과 추정
- 날짜 기반 자동 expiry
- Runtime image/engine release certification 축을 이번 결정에서 새로 도입
