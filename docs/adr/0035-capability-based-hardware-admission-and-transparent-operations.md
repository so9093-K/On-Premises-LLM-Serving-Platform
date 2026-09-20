# ADR-0035: Capability-based hardware admission and transparent operations

- Status: Accepted
- Date: 2026-09-20
- Refines: [ADR-0034](./0034-main-model-host-resource-variant.md), [ADR-0033](./0033-qualification-status-promotion-contract.md), [ADR-0032](./0032-qualification-evidence-v1.md)

## Context

ADR-0034 introduced `resource_variants` after RTX 4090 24GB live measurements showed that the
reference-host resource policy from RTX 6000 Ada 48GB could not be transferred unchanged. That
decision correctly prevented a selected 24GB override from silently falling back to the 48GB
reference command.

The boundary can be misread, however, as a hardware allowlist:

- a GPU model name can appear to decide whether a Main Model is supported,
- the absence of direct qualification evidence can appear to mean unsupported,
- every new GPU can appear to require a new variant and a new qualification run before use.

That is not the platform goal. Hardware identity is useful provenance, but the platform must remain
able to accept new hardware when the deployment/runtime contract and resource requirements are
satisfied.

The Control Plane also already records switch stages, but exposing a raw stage or spinner is not
enough for long-running operations. Operators need to know what is being attempted, why it is
needed, the current stage, failure impact, and the result.

## Decision

### 1. Hardware identity is observation, not admission authority

GPU product name, UUID, driver, memory size, and similar fields are observed runtime facts and
qualification provenance. They are not a primary allowlist for Main Model support.

Main Model execution eligibility is owned by:

1. deployment/runtime compatibility,
2. resource admission and runtime feasibility,
3. the selected Main Model profile contract,
4. runtime validation after apply/start.

A previously unseen GPU is not unsupported merely because no record names that product.

### 2. Qualification evidence is not a hardware support permit

`qualification.status` remains profile-level release/validation evidence. Durable evidence records
describe where and under which conditions a contract was actually exercised.

The absence of direct evidence for a particular GPU model does not by itself make that GPU
incompatible. In particular:

- `no direct hardware evidence` is not equivalent to `unsupported hardware`,
- qualification evidence may increase confidence and support release/governance decisions,
- compatibility/resource admission remain the execution gate.

A new hardware model does not require a new profile-level qualification simply because its product
name is new.

### 3. `resource_variant` means an explicit resource-policy override

Existing IDs, including `rtx4090-24gb`, remain unchanged for historical and evidence stability.
Their semantic role is refined:

> A resource variant is a reviewed override for runtime resource knobs when the profile's reference
> resource policy is not appropriate for a host.

It is not a general GPU taxonomy and it is not a list of supported GPU products.

The reference profile command remains usable without a variant when the current host can satisfy
that policy. A new GPU does not require a new `resource_variant` if the reference policy is
feasible.

If an operator explicitly selects `MAIN_MODEL_RESOURCE_VARIANT`, the existing fail-closed rule is
retained: a profile that does not declare that selected override must not silently fall back to the
reference policy. This protects the RTX 4090 24GB case and other hosts where the operator has
explicitly stated that a different resource policy is required.

### 4. New hardware follows capability/resource discovery, not product registration

The intended flow for new hardware is:

```text
observe runtime hardware
        ↓
deployment/runtime compatibility
        ↓
resource admission / feasibility
        ↓
reference policy fits?
   ├─ yes → start/apply → runtime validation
   └─ no  → matching reviewed override?
              ├─ yes → apply override → runtime validation
              └─ no  → bounded tuning/measurement → add override if actually needed
```

A qualification run may then be produced when durable certification evidence is useful. It is not
the prerequisite that makes an otherwise compatible GPU "supported".

### 5. Operations must be explainable before, observable during, and auditable after

Long-running Control Plane operations must provide operator-facing meaning, not only raw logs.

Before execution, the UI should identify the requested change and any confirmation requirement.
During execution, it should project the existing operation stage into a concise human-readable
description. After execution, it should show the final status, failure/rollback impact when
applicable, and the relevant evidence/observation references available from the API.

Raw logs remain diagnostic detail, not the primary explanation surface.

### 6. UI wording must keep support, compatibility, and evidence separate

The Console must not present profile qualification as a GPU support verdict.

Preferred wording distinguishes:

- **Compatibility** — whether the current deployment/runtime contract can attempt the profile,
- **Profile evidence** — whether the profile has repository-governed qualification evidence,
- **Resource policy** — reference policy or the explicit selected resource override,
- **Operation progress** — what the controller is doing now.

An `unverified` confirmation must explain that it concerns profile qualification evidence, not a
claim that the current GPU is unsupported.

## Consequences

- Existing RTX 4090 resource safety remains fail-closed when its override is explicitly selected.
- RTX 6000 Ada evidence remains valid historical/current evidence without becoming a hardware
  allowlist.
- RTX A6000 or any future GPU does not require a new qualification solely because the product name
  is different.
- New resource variants are introduced only when an actually different runtime resource policy is
  required.
- GPU-specific Main Model profiles, hardware-class catalogs, and GPU × model qualification matrices
  remain unnecessary.
- The Console can reuse existing switch operation stages for transparent progress without creating a
  second workflow state machine.

## Non-goals

- Automatically deriving safe vLLM tuning values from GPU product names.
- Removing runtime validation or rollback.
- Silently applying a selected resource override to profiles that do not declare it.
- Renaming existing immutable evidence IDs.
- Treating qualification evidence as irrelevant; it remains durable validation/governance evidence.
