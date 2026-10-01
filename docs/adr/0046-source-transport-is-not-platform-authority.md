# ADR-0046: Source transport is not a platform authority

## Status

Accepted

## Date

2026-10-01

## Context

ADR-0037 removed the repository-owned remote release state machine but intentionally kept a deterministic source ZIP and release manifest as a separate artifact concern.

After remote deployment was removed, that package no longer had a repository-owned deployment consumer. The remaining subsystem consisted of a dedicated payload resolver/materializer, ZIP writer and verifier, release-manifest/provenance formats, unit tests, documentation and a CI step that built the package and discarded it. GitHub Releases also had no published release assets using this format.

The platform already has distinct authorities for the information the package duplicated:

- Git commit/tree identifies source.
- `VERSION` and `pyproject.toml` identify the project/Python package version.
- Platform and Unified vLLM image contents are promoted by immutable registry digest.
- Runtime convergence is owned by the target-aware local lifecycle and Control Plane.
- CI validates application/contracts, the Control Plane frontend and a runnable Platform image.

Keeping a repository-specific source transport therefore adds another artifact lifecycle without changing deployment correctness.

## Decision

### 1. The repository does not own a source ZIP transport contract

Remove `make package`, `scripts/build/package_release.sh`, the release payload resolver/materializer and their dedicated tests.

The repository does not define `RELEASE_MANIFEST.json`, `RELEASE_PROVENANCE.json` or another source-archive identity format.

### 2. Git owns source identity and external transport may archive it

A source snapshot is identified by its Git commit/tree. If an external automation, audit process or user needs an archive, that transport is produced from the selected Git source outside the platform contract.

This does not create a second deployment authority. Applying source on a host still converges through the canonical target lifecycle.

### 3. Immutable image digest remains the deployable artifact identity

Platform and model-runtime images keep their existing build and publish boundaries. A published immutable registry digest identifies the image content used by a deployment.

`scripts/lib/source_provenance.sh` remains because Platform image build labels record source revision and clean/dirty state. It no longer serves a source-ZIP manifest.

### 4. Package-only process inputs are not active configuration

No runtime, CI or operator command consumes package naming/output overrides. Existing persistent-env cleanup entries may remain as migration tombstones so old `.env` files do not preserve meaningless keys, but those entries are not active process contracts.

The existing `EXPOSURE_MODE` migration guard is unrelated and remains fail-closed because it protects an old network posture from being silently reinterpreted.

### 5. CI validates product artifacts, not an unused transport implementation

The required CI gate continues to validate:

- application and repository contracts on supported Python minors,
- Control Plane source/generated assets,
- Platform image build and smoke.

It does not build a source archive solely to prove that source-archive code still works.

## Consequences

| Positive | Negative |
|---|---|
| Removes a second artifact lifecycle with no deployment consumer. | Consumers outside the repository cannot rely on the removed custom ZIP/manifest format. |
| CI time and test surface correspond more directly to product/runtime contracts. | External automation that needs a source archive must choose and own its transport. |
| Git source identity and immutable image identity have separate, clear authority. | The repository no longer provides a custom per-file source payload hash manifest. |
| Package-only compatibility and documentation stop generating additional maintenance work. | Historical ADR/CHANGELOG entries still mention the removed format as history. |

## Operational impact

Normal development, `make up`, Control Plane mutation, image build and runtime validation are unchanged.

There is no `make package` command. Source consumers use the selected Git revision; deployment consumers use the existing target lifecycle and immutable image references.

## Migration notes

- External automation that invoked `make package` should archive/checkout the selected Git revision itself or use its source-control provider's archive mechanism.
- Do not reintroduce a repository-owned source transport unless a concrete consumer and failure mode require a stable archive contract.
- Generic `.env` removed-key cleanup may continue to delete old package/deployment-only keys without treating them as active configuration.

## Related

- [ADR-0037](0037-local-lifecycle-deployment-authority.md)
- [ADR-0039](0039-operator-intent-lifecycle-and-diagnostics.md)
- [9. 자동화 경계](../09_cicd.md)
- [10. 배포](../10_deployment.md)
