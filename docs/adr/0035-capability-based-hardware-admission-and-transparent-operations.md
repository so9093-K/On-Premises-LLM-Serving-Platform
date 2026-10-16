# ADR-0035: 하드웨어 실행 적합성 판단과 운영 과정의 투명성

- Status: Accepted
- Date: 2026-09-20
- Refines: [ADR-0034](./0034-main-model-host-resource-variant.md)
- Partially superseded by: [ADR-0042](./0042-remove-qualification-evidence-and-benchmark.md) (영속 Qualification 근거 관리 부분)

## Context

RTX 4090 24GB 실측 결과, RTX 6000 Ada 48GB 기준 호스트의 자원 정책을 그대로 적용할 수 없었다.
이에 ADR-0034는 `resource_variants`를 도입했다. 운영자가 24GB용 Override를 선택한 경우
48GB 기준 명령으로 조용히 되돌아가지 못하게 한 것은 올바른 보호 조치다.

그러나 이 규칙을 하드웨어 허용 목록으로 오해할 수 있다.

- GPU 제품명만으로 Main Model 지원 여부가 결정된 것처럼 보일 수 있다.
- 해당 GPU에서 직접 검증한 `verified` 선언이 없으면 미지원으로 해석될 수 있다.
- 새로운 GPU마다 별도 Variant와 Qualification 검증이 선행돼야 하는 것처럼 보일 수 있다.

이는 플랫폼의 목적이 아니다. 하드웨어 식별 정보는 관측 출처를 설명하는 데 유용하지만,
현재 배포·Runtime 계약과 자원 요구사항을 충족하는 새 하드웨어를 허용할 수 있어야 한다.

Control Plane은 이미 모델 전환 단계를 기록하고 있다. 그러나 오래 걸리는 작업에서
원시 단계 값이나 로딩 표시만 노출하는 것으로는 부족하다. 운영자는 무엇을 시도하는지,
왜 필요한지, 어디까지 진행됐는지, 실패 시 영향과 최종 결과를 알아야 한다.

## Decision

### 1. 하드웨어 식별 정보는 관측값이며 실행 허용 권한이 아니다

GPU 제품명, UUID, 드라이버, 메모리 크기 등은 실제 Runtime에서 관측한 사실이다.
이를 Main Model 지원 여부를 판단하는 기본 허용 목록으로 사용하지 않는다.

Main Model 실행 적합성은 다음 계약을 함께 따른다.

1. 배포 환경과 Runtime의 호환성
2. 자원 Admission과 실제 실행 가능성
3. 선택한 Main Model Profile 계약
4. 적용·시작 후 Runtime 검증

이전에 관측하지 않은 GPU라는 이유만으로 미지원으로 판단하지 않는다.

### 2. Qualification은 하드웨어 지원 허가증이 아니다

`qualification.status`는 관리자가 실제 하드웨어에서 해당 Profile을 검증했다고
선언하는 **Profile 수준의 값**이다(ADR-0042).
해당 GPU 제품에서 직접 검증한 기록이 없다는 사실만으로 GPU를 비호환으로 판단하지 않는다.

- '이 GPU에서 직접 검증하지 않음'은 '지원하지 않는 하드웨어'와 다르다.
- 실행 허용의 판단 근거는 계속 호환성과 자원 Admission이다.
- 새 GPU 제품명만을 이유로 별도 Profile Qualification을 요구하지 않는다.

### 3. `resource_variant`는 명시적으로 검토된 자원 정책 Override다

`rtx4090-24gb` 등 기존 식별자는 과거 기록과의 호환성을 위해 유지한다.
다만 의미를 다음처럼 명확히 한다.

> Resource Variant는 해당 호스트에 Profile의 기준 자원 정책이 적합하지 않을 때
> 사용하는, 검토된 Runtime 자원 옵션의 명시적 Override다.

Variant는 GPU 제품 분류 체계도, 지원 제품 허용 목록도 아니다.
현재 호스트가 기준 정책을 충족한다면 새 GPU라도 Variant 없이 사용할 수 있다.

운영자가 `MAIN_MODEL_RESOURCE_VARIANT`를 명시적으로 선택한 경우에는
기존 Fail-Closed 규칙을 유지한다. 선택된 Override를 선언하지 않은 Profile에
기준 정책을 조용히 적용해서는 안 된다. 이는 RTX 4090 24GB처럼 다른 자원
정책이 필요하다고 운영자가 선언한 호스트를 보호한다.

### 4. 새 하드웨어는 제품 등록이 아닌 기능·자원 확인 과정을 따른다

```text
Runtime 하드웨어 관측
        ↓
배포 환경·Runtime 호환성 확인
        ↓
자원 Admission 및 실제 실행 가능성 확인
        ↓
기준 자원 정책으로 실행 가능한가?
   ├─ 가능 → 시작·적용 → Runtime 검증
   └─ 불가 → 검토된 Override가 있는가?
              ├─ 있음 → Override 적용 → Runtime 검증
              └─ 없음 → 제한된 범위의 튜닝·실측 → 실제 필요할 때 Override 추가
```

관리자는 이후 Profile을 `verified`로 선언할 수 있다. 그러나 이 선언 자체가
원래 호환되는 GPU를 '지원되는 하드웨어'로 바꾸는 선행 허가 조건은 아니다.

### 5. 운영 작업은 실행 전 설명, 실행 중 관측, 실행 후 감사가 가능해야 한다

오래 걸리는 Control Plane 작업은 원시 로그만이 아닌 운영자에게 의미 있는 정보를 제공한다.

- 실행 전: 요청한 변경과 추가 확인이 필요한 이유
- 실행 중: 기존 Operation Stage를 간결한 사람이 이해할 수 있는 설명으로 투영한 진행 상태
- 실행 후: 최종 상태, 실패·Rollback 영향 및 API가 제공하는 관련 관측 정보

원시 로그는 상세 진단 수단이며, 작업 의미를 설명하는 주된 화면을 대체하지 않는다.

### 6. UI는 지원 여부·호환성·Qualification을 구별한다

Console에서 Profile Qualification을 GPU 지원 여부의 판정처럼 표현하지 않는다.

- **호환성(Compatibility)**: 현재 배포·Runtime 계약상 해당 Profile을 시도할 수 있는가?
- **Qualification**: 관리자가 Profile을 실제 장비에서 검증했다고 선언했는가?
- **자원 정책(Resource Policy)**: 기준 정책 또는 명시적으로 선택한 자원 Override
- **작업 진행(Operation Progress)**: Controller가 지금 수행하는 작업

`unverified` 확인은 Profile의 Qualification 선언에 대한 것임을 설명해야 한다.
현재 GPU를 지원하지 않는다는 주장으로 바꾸지 않는다.

## Consequences

- RTX 4090용 Override가 명시적으로 선택된 경우의 Fail-Closed 보호를 유지한다.
- RTX 6000 Ada에서 검증된 Profile은 그 GPU를 하드웨어 허용 목록으로 만들지 않고도
  `verified` 상태를 유지할 수 있다.
- RTX A6000 등 다른 GPU는 제품명이 다르다는 이유만으로 새 Qualification을 요구하지 않는다.
- 실제로 다른 Runtime 자원 정책이 필요할 때에만 새 Resource Variant를 도입한다.
- GPU 제품별 Main Model Profile, 하드웨어 등급별 Catalog, GPU×모델 Qualification 표를
  별도로 둘 필요가 없다.
- Console은 새 Workflow 상태 머신을 만들지 않고 기존 전환 Stage로 작업 진행을 설명할 수 있다.

## Non-goals

- GPU 제품명에서 안전한 vLLM 튜닝 값을 자동 산출하는 기능
- Runtime 검증 또는 Rollback 제거
- 선택된 Override를 선언하지 않은 Profile에 해당 설정을 암묵적으로 적용
- 기존 Resource Variant 식별자 변경
