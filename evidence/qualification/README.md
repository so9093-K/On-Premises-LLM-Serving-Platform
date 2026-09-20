# Qualification evidence receipts

이 디렉터리는 Main Model `qualified_run`으로 승격된 최소 실행 증빙을 소유한다.

`reports/runtime/`의 runtime-validation JSON/Markdown은 조사와 실행 확인을 위한 임시 산출물이며
Git history가 소유하지 않는다. 새 qualification은 해당 report와 현재 Main Model/runtime/hardware
관측을 결합해 candidate receipt를 만들고, review를 거쳐 이 디렉터리 아래
`runs/<record-id>.json`으로 승격한다.

receipt v1은 다음 형태를 사용한다.

```json
{
  "version": 1,
  "kind": "qualification_run_receipt",
  "record": {
    "kind": "qualified_run"
  }
}
```

`record`는 `configs/qualification_evidence.yaml`의 대응 record에서 `source`만 제외한 값과
정확히 같아야 한다. repository validator가 receipt와 catalog drift를 거부한다.

Receipt는 **그 실행 당시의 사실을 보존하는 immutable history**다. 이후 GPU/driver/resource policy가
바뀌거나 qualification check registry가 확장되어도 과거 receipt를 현재 값으로 다시 쓰지 않는다.

현재 Main Model profile의 `verified` 근거로 재사용 가능한지는 receipt 보존 여부와 별도로 판단한다.
Profile/model/revision/capability와 Main Model deployment target이 맞아야 하며, `qualified_run`은
현재 required check를 모두 통과한 기록이어야 한다. GPU 이름·UUID·driver, runtime fingerprint,
`resource_variant`, `validated_at`은 provenance이며 그 값만 달라졌다는 이유로 profile-level
qualification을 무효화하지 않는다. 세부 경계는
[ADR-0036](../../docs/adr/0036-qualification-evidence-reuse-and-invalidation.md)을 따른다.

runtime의 `image_digest`는 registry/distribution에서 재식별할 수 있는
`sha256:<64 hex>` digest다. Docker daemon의 local `image_id`와 같은 개념으로 취급하지
않으며, 실행 artifact의 distribution digest를 단일하게 관측하지 못하면 값을 추측하지 않는다.

receipt에는 raw prompt, 모델 출력, 인증 token, 전체 Docker/NVIDIA dump나 대형 log를 저장하지
않는다. 그런 실행 산출물은 repository evidence의 범위가 아니다.
