# ADR-0034: Main Model host resource variant

- Status: Accepted
- Date: 2026-09-20
- Extends: [ADR-0018](./0018-gpu-vram-admission-and-per-profile-runtime-image.md), [ADR-0032](./0032-qualification-evidence-v1.md)
- Refined by: [ADR-0035](./0035-capability-based-hardware-admission-and-transparent-operations.md)

## Context

> **Terminology refinement:** this ADR originally used "GPU class" to explain the RTX 4090
> incident. ADR-0035 narrows the meaning: `resource_variant` is an explicit runtime
> resource-policy override, not a supported-GPU taxonomy. A new GPU product does not require a new
> variant when the reference policy is feasible.

Main Model profile은 `configs/main_model_profiles.yaml`에서 model identity(`model_id`,
`revision`), capability, Gateway 계약, 그리고 vLLM 실행 인자를 한 덩어리로 소유한다. 그 실행
인자의 자원 값은 reference host인 RTX 6000 Ada 48GB에서 실측해 정한 것이다.

2026-09-19에 `gemma4-e4b-it`를 RTX 4090 24GB에 그대로 기동하자 CUDA OOM으로 engine
초기화가 실패했다. 원인을 실측으로 좁힌 결과는 다음과 같다.

GPU budget은 VRAM 총량 대비 **비율**(`--gpu-memory-utilization`, `configs/gpu_budgets.yaml`의
`avoid_above`)로 표현되는데, 그 비율이 덮어야 하는 것 — 모델 weight, CUDA context, prefill
activation workspace, reserve headroom — 은 **절대량**이다. 그래서 48GB에서 정한 비율은
24GB로 이전되지 않는다. `0.76`은 임의의 값이 아니라 stack budget(`0.76 + 0.04 + 0.06 +
0.065 = 0.925 <= 0.93`)에서 역산된 값인데, 같은 비율이 48GB에서는 36.4 GiB, 24GB에서는
18.2 GiB를 뜻하고 E4B의 weight 15.23 GiB는 어느 쪽에서도 같다.

RTX 4090 실측(vLLM 0.25.1, 동일 image·revision, 격리 runtime):

| max_model_len | seqs | batched | 결과 | KV 가용 | KV token |
|--------------:|-----:|--------:|------|--------:|---------:|
| 65000 | 1 | 4096 | 기동 | 2.12 GiB | 117,849 |
| 65000 | 4 | 4096 | 기동 | 2.12 GiB | 117,849 |
| 65000 | 4 | 8192 | 기동 | 1.69 GiB | 82,686 |
| 65000 | 4 | 16384 | 실패 | 0.78 GiB | - |
| 65000 | 4 | 50000 | 실패 | - | - |

`max_model_len=65000`은 24GB에서도 그대로 기동한다. `max_num_seqs`는 boot 메모리에 거의
영향이 없다(4,096에서 seqs 1과 4의 KV가 동일). 실제 제약은 prefill activation workspace를
정하는 `max_num_batched_tokens` 하나였다. 즉 host의 VRAM·runtime 자원 조건이 바뀔 때 달라져야 하는 것은
profile identity가 아니라 **그 identity를 어떤 자원 정책으로 서빙하는가**였다.

기존 수단으로는 이를 표현할 수 없었다.

- `MAIN_MODEL_GPU_MEMORY_UTILIZATION`(ADR-0018)은 비율 하나만 덮는다. 이번 원인인
  `max_num_batched_tokens`는 덮지 못한다.
- profile을 복제해 `gemma4-e4b-it-24gb`를 만들면 약 100줄의 `gateway_policy`가 함께 복제되어
  drift 위험이 생기고, 같은 모델이 두 identity로 갈라진다.
- 값을 env로만 덮으면 실행은 되지만 **어떤 자원 정책을 검증했는지가 증거에 남지 않는다.**
  ADR-0032가 막으려던 종류의 거짓 증거가 그대로 생긴다.

## Decision

### 1. Profile은 필요한 resource-policy override를 선언한다

profile에 선택적 `resource_variants` 블록을 둔다. variant는 자원 knob만 덮을 수 있다.

```yaml
resource_variants:
  rtx4090-24gb:
    display_name: NVIDIA GeForce RTX 4090 24GB
    max_num_batched_tokens: 4096
```

덮을 수 있는 key는 `max_model_len`, `max_num_seqs`, `max_num_batched_tokens`,
`gpu_memory_utilization` 넷으로 고정한다. 그 밖의 key는 로드 시점에 거부한다. variant는
model identity, capability, Gateway 계약을 바꿀 수 없다 — 바꿀 수 있게 되는 순간 그것은
variant가 아니라 다른 profile이다.

catalog는 선택되지 않은 variant도 전부 검증한다. 오타는 그 host에 배포되는 순간이 아니라
catalog를 읽는 모든 경로에서 즉시 드러나야 한다.

### 2. 선택은 host의 operator env가 한다

`MAIN_MODEL_RESOURCE_VARIANT`는 이 host에 필요한 명시적 resource-policy override를 고른다.
비어 있으면 GPU 제품명이 알려졌다는 뜻이 아니라 profile의 reference policy로 기동한다.

Fail-closed는 두 층위에서 성립한다.

- 어떤 profile도 그 id를 선언하지 않으면 catalog 로드가 실패한다(오타 방지).
- operator가 `MAIN_MODEL_RESOURCE_VARIANT`로 override를 명시했는데 **개별 profile**이
  그 id를 선언하지 않으면, 그 profile은 reference policy로 fallback할 수 없다. boot 해석과
  switch 요청이 모두 거부하며, switch는 `MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED`로 응답한다.

두 번째가 없으면 명시적으로 선택한 resource override는 실질적으로 fail-closed가 아니다.
`rtx4090-24gb`를 선언한 profile만 override 값으로 기동하고 나머지는 reference 값으로 남아,
전환 한 번으로 reference policy가 맞지 않는 24GB 환경에 48GB 기준 자원 정책이 적용된다. weight만 25.8 GiB인 26B profile에서 이는 곧바로 OOM
경로다.

`confirm_unverified`는 qualification 축의 확인이지 자원 정책의 확인이 아니므로 이 거부를
우회하지 못한다. boot reconcile이 그 flag를 켜고 같은 경로를 지나기 때문에, 우회가 가능하면
재기동만으로 reference 정책이 다시 적용된다.

운영상 결과: operator가 variant를 명시하면 그 override를 선언한 profile만 부팅 대상이 된다.
`default_profile`이 해당 override를 선언하지 않으면 `MAIN_MODEL_BOOT_PROFILE`로 적용 가능한
profile을 명시해야 한다. 이는 hardware support 판정이 아니라 reference policy fallback을
막기 위한 자원 정책 안전 경계다. 이전 host 설정에서 넘어온 persisted active profile이 지원 대상이
아닌 경우에도 catalog에서 사라진 profile과 같은 방식으로 기동이 멈춘다 — 운영자가 의도를
다시 말하기 전까지 검증된 적 없는 자원 정책으로 기동하지 않는다.

variant가 적용된 뒤에도 `MAIN_MODEL_GPU_MEMORY_UTILIZATION`이 마지막 발언권을 갖는다.
variant는 catalog가 소유한 검토된 resource policy이고, 그 env는 단일 호스트용 escape hatch다.

### 3. Engine 한도와 Gateway admission은 variant 적용 뒤에도 일치한다

variant가 `max_model_len`을 옮기면 catalog loader가 같은 값을
`gateway_policy.request_limits.max_model_len`에 투영한다. 둘이 갈라지면 Gateway가 engine이
곧바로 거부할 요청을 통과시키거나, 반대로 서빙 가능한 요청을 막는다.

### 4. 적용된 variant는 qualification identity의 일부다

적용된 variant id는 active profile snapshot과 qualification context에 실리고, durable
`qualified_run`의 `subject.resource_variant`로 기록된다. reference host 정책으로 검증한 run은
이 key를 갖지 않으므로 기존 record 형태는 그대로다.

시작/종료 snapshot 사이에 variant가 바뀌면 그 run은 버린다. profile이 바뀐 경우와 같은
이유다 — 무엇을 검증했는지 말할 수 없는 run이다.

이 결정이 없으면 "`gemma4-e4b-it`가 `linux-nvidia-dynamic`에서 통과했다"는 기록이 어떤 자원
정책에서 나온 것인지 말하지 못하고, 48GB reference 값으로 읽힌다.

## Consequences

- 같은 model/revision을 서로 다른 VRAM 조건에서 서빙해도 profile identity는 하나로 유지된다.
- 24GB용 증거와 48GB용 증거가 evidence 수준에서 구분된다.
- Host가 variant를 선언하지 않으면(비어 있으면) 모든 profile이 종전과 같이 선택 가능하다.
  기존 evidence record도 변화가 없다.
- resource override 값은 여전히 실측으로만 채운다. variant는 측정 결과를 적을 자리를 만들 뿐,
  값을 추론하지 않는다.

## 범위 밖

이번 결정은 Main Model 격리 실측까지만 다룬다. 같은 24GB host에 embedding 2종과 risk
detector를 함께 상주시키는 구성은 검증하지 않았다. 현재 비율 예산으로는 4090에서 여유가
약 730 MiB에 불과하고 `gpu_budgets.yaml`의 `reserve_gib.hard_minimum` 3.5 GiB를 만족하지
못한다. support runtime 예산을 절대량 기준으로 다시 세우는 일은 별도 결정으로 남긴다.
