# Qualification status promotion

`qualification.status` 승격은 durable qualification evidence 저장과 분리된 review boundary다.
이 문서는 ADR-0033을 따르는 operator 절차만 설명한다. 기존 compatibility 상태,
switch-confirmation 계약, public/Admin API 또는 historical evidence를 변경하지 않는다.

## Preconditions

승격 대상 profile에는 현재 profile tuple과 정확히 일치하고 **검토 대상 deployment target에서**
생성된 repository-owned `qualified_run` evidence가 있어야 한다. Evidence는 `passed`여야 하며
현재 required stable check를 모두 통과해야 한다. 선택한 target은
`configs/main_model_profiles.yaml`을 Main Model catalog로 사용해야 한다. `legacy_backfill`은
기존 verified history를 보존하기 위한 자료이며 신규 `unverified -> verified` 승격 근거가 아니다.

`resource_variant`는 qualification evidence가 어떤 resource policy에서 생성됐는지 남기는
provenance다. Profile-level `qualification.status` 승격은 GPU 제품이나 resource variant별
지원 허가가 아니므로, 같은 deployment target 안에서는 reference policy와 reviewed override
차이만으로 evidence를 배제하지 않는다.

먼저 repository 전체 계약을 확인한다.

```bash
make check
```

## 1. Review a plan

상태 변경 없이 현재 eligibility와 repository state를 묶은 plan을 생성한다.

```bash
python scripts/qualification/status_promotion.py \
  --profile <profile-id> \
  --target <deployment-target>
```

출력의 `deployment_target`, eligible qualified-run IDs와 `plan_digest`를 검토한다. 이 단계는
`configs/main_model_profiles.yaml`을 수정하지 않는다.

## 2. Apply exactly the reviewed plan

같은 checkout에서 검토한 digest를 명시적으로 전달한다.

```bash
python scripts/qualification/status_promotion.py \
  --profile <profile-id> \
  --target <deployment-target> \
  --apply \
  --confirm <plan_digest>
```

Apply 직전에 eligibility와 profile/evidence/deployment-target/check-registry Source of Truth
digest를 다시 계산한다. 검토 이후 profile, qualification evidence, deployment target 계약 또는
required check registry가 달라졌다면 digest가 일치하지 않아
fail-closed하며 status를 변경하지 않는다. Exact reviewed plan이 여전히 유효한 경우에만
대상 profile의 `qualification.status` scalar를 `unverified`에서 `verified`로 변경한다.

## 3. Review and validate the repository diff

```bash
git diff -- configs/main_model_profiles.yaml
make check
```

예상 diff는 대상 profile의 `qualification.status` 변경뿐이다. Compatibility,
switch-confirmation, model/revision/capability identity 또는 evidence를 함께 바꿔야 한다면
이 status-promotion 작업에 섞지 말고 원인을 별도 변경으로 다룬다.

승격 diff는 일반 PR로 제출하고 required CI Gate가 모두 성공한 경우에만 merge한다.
CI 성공은 reviewed plan 확인을 대체하지 않는다.
