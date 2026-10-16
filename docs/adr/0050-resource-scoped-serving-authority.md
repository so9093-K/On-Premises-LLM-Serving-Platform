# ADR-0050: GPU resource scope, placement evidence and restart validation

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR-0018](0018-gpu-vram-admission-and-per-profile-runtime-image.md), [ADR-0031](0031-runtime-controller-docker-authority-boundary.md), [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md), [ADR-0037](0037-local-lifecycle-deployment-authority.md)

## Context

The original controller shares one GPU between Main and secondary runtimes. Its
GPU admission uses a sum of vLLM reservation **fractions**. Those fractions are
meaningful only within the same physical GPU. A model can also require several
GPUs. More GPU capacity must not turn an implicit host-wide scalar budget into a
silently incorrect cluster-wide decision.

The existing dynamic Linux lifecycle has **one local Docker authority** scoped
to a Compose project and a local file-based state machine. File locks and
process-local asyncio locks do not protect a distributed host fleet. We must not
claim actual remote execution/failover merely by adding a `host_id` field.

A runtime restarted outside the Runtime Controller could previously continue
receiving Gateway traffic during failed canary revalidation. If the validation
fingerprint did not exist, the reconcile loop would simply record the observed
container start time without a canary.

## Decision

### 1. GPU budgets are scoped to physical resources, not aggregated hosts

`GpuResourceId(host_id, device_id)` is the reservation identity. The host is
not the GPU. Two GPUs on one host represent two distinct budgets, as do GPUs with
the same device ID on different hosts. A fleet with one host is the same
resource model as a fleet with more hosts; a single pool is a valid projection.

`gpu_budget.plan_activation` remains the unique per-GPU admission/eviction
authority. Its existing controller-local default is a compatibility projection
for the current **one-GPU** Docker target, not a discovery result or portable
physical GPU identity. Mixing participants from different pools in this legacy
function is an error, not an invitation to add their fractions.

### 2. The caller explicitly establishes hardware eligibility

`resource_placement.plan_placement` accepts an inventory of GPU pools and
eligible placement candidates, including candidate groups that reserve multiple
GPUs. Each demand carries a resolved fraction for that *particular* GPU.

The planner never infers model compatibility, tensor parallel support,
interconnect quality, or memory fit from GPU product names. Those must be
qualified by the caller/active runtime policy. It uses the existing per-pool
admission authority and combines the resulting victim identities without
evicting one shard of a multi-GPU runtime.

A running runtime may not silently migrate its GPU set. Explicit stop,
transition and runtime revalidation are required.

### 3. Preview evidence does not grant mutation authority

Placement preview produces a deterministic digest of pool generations,
reservations, candidates and policy inputs. A changed snapshot invalidates a
previous plan. An eviction plan is not admissible until explicitly authorized.

**This is not an inter-host transaction.** An actual multi-host apply requires
one authoritative state/lease owner with atomic compare-and-reserve and fencing
of stale executors. `require_current_placement` must execute under that
owner's lock/CAS through the reservation commit. Recomputing a digest outside
the lock does not provide race safety. No fake in-memory multi-host lock, new
remote Docker permission, global registry, or distributed controller is created.

This PR deliberately does not advertise distributed serving as implemented.
The existing Linux managed deployment remains controller-local; static
deployment's lifecycle authority remains external. Public `/v1/*` contracts,
logical `local-main` and operator commands remain unchanged.

### 4. Local Main Model state changes have monotonic revisions

`MainModelStateStore` remains the sole persistent owner of local Main Model
control. Its state generation advances on each committed update. Stale direct
writers are rejected, and a controller may use `compare_and_update` to commit
only against a previously observed generation. Existing schema-v1 state
without a generation starts at revision zero **without resetting intent**.
Invalid generation data fails closed.

The atomicity guarantee covers processes using the **same local state
directory and filesystem lock**. It does not extend to separate remote
hosts and cannot replace distributed leases/fencing.

### 5. Runtime execution is an allowlisted local capability

Runtime transition and GPU admission remain decisions of the Runtime
Controller; only the Docker Runtime Executor maps an allowed service to
project-scoped Docker container identity and performs start/stop/status.
There is no separate state machine in this executor. The Main Model
switching backend remains independently owned by the Main Model Manager.
Log collection continues to use read-only scoped Docker observations.

The service allowlist is projected from canonical Runtime Topology and
the Main Model Profile. An unrecognized service is rejected before any
Docker call, and both the Docker query and its results are checked against
the declared Compose project. The executor never accepts an arbitrary
container ID, image, command, volume, mount, network or remote endpoint
from an API caller. This does not sandbox Docker socket privileges.

The current adapter controls local Docker only; an actual remote executor
would require explicit trust, authentication, fencing and ownership
contracts before being enabled.

### 6. Out-of-band Runtime replacement loses validation

When reconciliation observes a new or missing container instance, or finds no
previously validated identity, it closes the Main Model request gate before
canary verification. It reopens only after the expected observed container
identity is rechecked at the end of successful validation. If identity changes
during canary, fingerprint cannot be observed, or validation fails, the gate
remains closed and reconciliation follows its bounded retry/backoff policy.

This prioritizes truthful advertised serving capability over continued
requests to an unvalidated runtime. A transient Docker inspect failure alone
does not prove replacement and remains a diagnostic event.

## Consequences

- Single-GPU existing admission uses the same planner and priority policy.
- Runtime Control uses one permission-bounded Docker execution adapter instead of duplicating container ID lookups and mutation calls in the coordinator.
- Local Main Model state updates expose a monotonic revision without replacing the canonical ledger or inventing another state writer.
- One host with two GPUs, two hosts with one GPU each, and a multi-GPU
  candidate can be reasoned about without attaching deployment decisions to
  Docker container IDs.
- No automatic placement or distributed execution is exposed as supported
  until an authoritative inventory, durable reservation store and remote
  executor fencing are implemented and tested with real hosts.
- A model restarted outside the controller may produce a brief 503 window
  while it is revalidated. A failed canary does not reopen the gate.
- Percentage reservations are not a measured GPU memory fit guarantee.
  Real-device execution qualification remains distinct from planner tests.

## Verification

- Per-pool non-mixing, eligibility, deterministic placement, multi-device
  candidates, victim grouping, changed-generation invalidation, no silent move.
- Docker executor's service allowlist, Compose project scope, no-op missing container, ambiguous identity and lifecycle mutations.
- Single-GPU admission regressions and existing runtime transition tests.
- Local state revision compare-and-update, stale writer rejection and migration of legacy schema-v1 snapshots.
- Reconciliation with a missing identity, out-of-band restart, failed canary,
  instance replacement during validation, retry/backoff and success recovery.
- Project-defined `make check`, generated contract drift checks and Linux
  managed runtime validation when appropriate hardware is available.

## Related

- [ADR-0030](0030-target-architecture-state-and-artifact-boundary.md)
- [ADR-0031](0031-runtime-controller-docker-authority-boundary.md)
- [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md)
- [ADR-0038](0038-resource-aware-secondary-runtime-topology.md)
