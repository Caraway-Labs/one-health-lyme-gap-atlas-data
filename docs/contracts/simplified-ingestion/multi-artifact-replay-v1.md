# Run-pinned artifact member replay v1

Status: proposed for human review under Story #432 and [ADR 0038](../../adr/0038-run-pinned-artifact-member-replay.md). Owner: Atlas data stewardship and engineering. This extends the [simplified-ingestion interface freeze](interface-freeze.md) and [ADR 0037](../../adr/0037-binary-replay-and-bounded-ingestion-revisions.md). It does not define a source product, scientific transformation, or publication decision.

## Identity and capture

`AcquireResult.artifacts` is the bounded set of independent, source-faithful `AcquisitionArtifact` responses. Each has a nonempty, unique `name` within one ingestion run. The `(ingestion_run_id, name)` pair is the stable member key; `member_id` is SHA-256 of the UTF-8 name. Name and member ID do not depend on enumeration order, content, or object-store URI. Duplicate names or IDs fail capture/replay. `request_purpose` is the member role. A role may describe several members, so role-only lookup must find exactly one or fail as ambiguous. Names are logical identifiers, not filenames to traverse; path separators and control characters are rejected.

Each persisted member records run ID, member ID, name, role, artifact ID, source URI, media type, SHA-256, byte count, available row count, and the private artifact URI where applicable. The primary member is the unique member whose digest and media type match `AcquireResult` and whose bytes match `raw_payload` (or its byte payload) when provided; no array position selects it. A missing or ambiguous primary fails capture. Existing one-artifact adapters synthesize `source-payload` as before and retain their legacy artifact ID and binary checkpoint APIs.

## Storage-neutral resolution

`ArtifactMemberStore.list_artifact_members(run_id)` returns metadata sorted by name. `load_artifact_member(run_id, name=... or role=...)` requires one exact match and verifies the retained byte count and SHA-256. No match, multiple role matches, duplicate identity, changed metadata, absent bytes, or bad checksum raises an error. The optional adapter `restore_artifacts(definition, run_id, store)` hook requests named members and reconstructs its validation/normalization input. Adapters without that hook keep the #426 `restore_raw_payload` and JSON checkpoint paths. The orchestrator checks the complete retained member set against the ACQUIRE checkpoint and verifies every member before the hook runs. A failed resume never calls `acquire` for a completed ACQUIRE stage.

## Local and governed persistence

Tier A file checkpoints store each member in its own `<run>.member-<member_id>.bin` file and matching metadata JSON. Reopening `FileCheckpointStore` in a new process reads those files only. Existing `<run>.artifact.bin` and its API remain for traditional single-binary runs. In-memory storage implements the same member interface for tests.

Tier B/C capture retains each source response separately in the existing private Spaces bucket and registers a separate `GOVERNANCE.RAW_ARTIFACTS` row and `GOVERNANCE.INGESTION_REQUESTS` row. The existing ACQUIRE run checkpoint holds the immutable member manifest. Named replay resolves the exact artifact ID and run in `RAW_ARTIFACTS`, checks request endpoint/role and artifact metadata against that manifest, enforces the configured private bucket/prefix, then verifies object bytes. New multi-member artifact and request IDs derive from the run and member name, independent of enumeration order. The legacy single-artifact IDs and `SOURCE_PAYLOAD` behavior remain. No schema migration or new storage service is required. The pre-V070 single-source fallback now refuses an ambiguous `SOURCE_PAYLOAD` set rather than choosing its earliest row.

## Resume, lineage, and limits

The ACQUIRE checkpoint links one run to every independently identified artifact. Its primary artifact remains the run-level `artifact_id` used by existing normalized record lineage; the complete member manifest separately identifies every input to the transformation. A future source-specific transformation must include the required member IDs/digests in its own methodology or output lineage as appropriate. This contract does not silently turn an auxiliary member into a single synthetic source artifact. Existing deterministic normalized partitions and immutable revision ledger are unchanged.

Fixture tests prove two distinct binary streams, restart at VALIDATE, restart after a partial NORMALIZE partition, missing/corrupt/duplicate/ambiguous members, reordering, and Snowflake/Spaces query shape. No NOAA or TIGER parser is introduced. This does not authorize DEV or PROD source execution, prove live Snowflake/Spaces runtime, or change #424 geometry semantics. A worker failure before ACQUIRE completes remains governed by the existing stage retry behavior; completed ACQUIRE stages never externally reacquire on replay failure.
