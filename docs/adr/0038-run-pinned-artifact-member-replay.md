# 0038: Run-pinned artifact member replay

Status: Proposed for protected review

Date: 2026-09-25

Decision owner: Atlas data stewardship and engineering

Story: #432; prerequisite to #198

## Context

ADR 0037 gave the canonical ingestion run one binary replay slot. `AcquisitionArtifact` already describes multiple source-faithful package members, and governed capture writes separate Spaces objects and `RAW_ARTIFACTS` rows, but resume cannot request an exact named member. Selecting the earliest artifact or reacquiring a mutable reference would make a two-input transformation irreproducible.

## Decision

Keep the existing `IngestionOrchestrator`, `AcquireResult`, private Spaces bucket, and run/checkpoint ledgers. Use the existing acquisition member name as a unique run-scoped key; derive a deterministic member ID from it. Retain a member manifest in the ACQUIRE checkpoint. Add a storage-neutral member enumeration and exact lookup interface to the existing checkpoint stores, with independent SHA-256 verification. An adapter may opt in with `restore_artifacts`; legacy adapters and the single-binary API are unchanged. For multiple members, stable artifact and request IDs depend on the run and member name, not capture order. Governed replay checks the exact run/artifact ledger row, request role/source endpoint, configured bucket/prefix, and object bytes. No new table or service is needed.

## Consequences

Each source response remains independently attributable while the existing primary artifact continues to anchor generic normalized rows. A multi-input consumer must preserve the auxiliary member IDs and digests in its source-specific transformation lineage. Corrupt, missing, duplicate, ambiguous, or replaced members fail closed after ACQUIRE completion. Verification reads one member at a time; an adapter may still hold an entire primary scientific binary as allowed by ADR 0037. No NOAA parsing, TIGER parsing, geometry change, or public release is included.

## Alternatives considered

An ordinal key was rejected because reordered enumeration could select different inputs. Bundling unrelated bytes was rejected because it erases independent source lineage. A new replay service or destructive migration was unnecessary because existing checkpoints and `RAW_ARTIFACTS` already supply run-pinned metadata and immutable object storage.

## Acceptance criteria

Two binary members survive a process restart and resume at VALIDATE or NORMALIZE, including a partial partition. Exact named lookup, independent checksums, reorder invariance, and fail-closed cases have automated fixture/local and Snowflake query-shape evidence. Existing #426 single-artifact regression tests remain green. Live DEV and PROD evidence remain separate governance steps.

## Rollout, observability, and rollback

Code and documentation only at this PR boundary. After human review and merge, the normal digest-based DEV path may exercise the capability under existing source approval and migration controls. No PROD execution is authorized here. Rollback stops new multi-member runs while retained immutable artifacts and checkpoint evidence remain available. The legacy single-artifact path is unchanged.

## Links to affected contracts and tests

`docs/contracts/simplified-ingestion/multi-artifact-replay-v1.md`; `docs/contracts/simplified-ingestion/interface-freeze.md`; `docs/adr/0037-binary-replay-and-bounded-ingestion-revisions.md`; `tests/test_multi_artifact_replay.py`; `tests/test_binary_partitioned_ingestion.py`.
