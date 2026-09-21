# ADR-0038: Resource-aware secondary runtime topology

- Status: Accepted
- Date: 2026-09-21
- Extends: [ADR-0018](./0018-gpu-vram-admission-and-per-profile-runtime-image.md), [ADR-0034](./0034-main-model-host-resource-variant.md), [ADR-0035](./0035-capability-based-hardware-admission-and-transparent-operations.md)
- Follows: [ADR-0037](./0037-local-lifecycle-deployment-authority.md)

## Context

RTX 4090 24GB live measurement showed that `gemma4-e4b-it` with its reviewed
`rtx4090-24gb` Main resource policy can serve with the two embedding runtimes, but adding
`prompt_injection_detector` is not feasible. The detector needs about 3.05 GiB including its
generation KV budget, while the remaining memory after Main + both embedding runtimes is lower.

The existing GPU planner uses relative `gpu_memory_utilization` reservations. That abstraction is
useful for ordinary admission, but it cannot safely infer this absolute-memory composition limit.
PR #136 therefore disabled the detector globally. That prevented the 24GB failure but also removed
a runtime that remains valid on the reference resource policy.

ADR-0035 separates hardware identity from resource feasibility: a GPU product name is not a support
allowlist. ADR-0037 also removed the duplicate remote deployment state machine, so resource-aware
topology now only needs to project through one canonical lifecycle.

## Decision

`configs/runtime_topology.yaml` owns reviewed secondary-runtime composition constraints through
`unavailable_with_main_resource_variants`.

The field means: while one of the named Main Model resource-policy overrides is selected, this
secondary runtime is unavailable in the effective topology. It does **not** mean that a GPU model
or driver is supported or unsupported, and it does not infer constraints from hardware names.

The declared topology remains the reusable capability/lifecycle contract. The effective topology
is produced by applying the explicitly selected `MAIN_MODEL_RESOURCE_VARIANT`:

- constrained runtimes become `enabled=false`, `required=false`, `controllable=false` in the
  effective projection only;
- startup profiles may remain target-neutral; unavailable entries are ignored when resolving a
  profile, while direct attempts to name an unavailable runtime fail closed;
- a remaining runtime may not depend on a prerequisite removed by the projection;
- referenced resource-variant IDs must exist in the Main Model profile catalog;
- operator-facing read projections may retain a constrained declared runtime as unavailable with a
  stable resource-policy reason, but that projection must not re-add it to controllable/start,
  readiness, detector, or public-model sets. The reason identifies the selected resource policy,
  not a GPU support classification.

The same effective topology must feed Gateway settings and `/v1/models`, Risk Signal Service
detector enablement, Runtime Controller controllability/admission inputs, Gateway desired-state
keys, compose-up disabled/deferred resolution, smoke checks, and live runtime validation.

The checked-in `model_list_response.schema.json` remains deployment-target neutral: its model IDs
and capability values are the union that this build may expose, while the array permits the Main-only
shape used by static targets and resource-constrained projections. Runtime validation, not the static
schema, owns the exact model set required by the current effective topology.

For the current measured case, `prompt_injection_detector` is declared active and controllable but
lists `rtx4090-24gb` as unavailable. Reference policy therefore restores the Prompt Injection
Detector, while the 24GB override preserves the safe PII/Secret-only risk path.

## Consequences

- A host/resource policy can remove an unsafe secondary runtime without globally deleting its
  capability or code path.
- Runtime Startup Profiles stay about operator startup intent instead of becoming hardware-class
  catalogs.
- Hardware provenance and qualification remain separate from runtime resource feasibility.
- Static percentage admission is not claimed to prove absolute-memory feasibility for every
  generation runtime.
- Adding a new constraint requires live evidence and review; a newly observed GPU product alone is
  not sufficient.

## Non-goals

- Automatic GPU product classification or hardware allowlists
- Replacing `configs/gpu_budgets.yaml` percentage admission
- Automatically deriving absolute VRAM requirements from model metadata
- Changing Main Model qualification evidence semantics
- Introducing a new Host Inventory or Serving Variant subsystem
