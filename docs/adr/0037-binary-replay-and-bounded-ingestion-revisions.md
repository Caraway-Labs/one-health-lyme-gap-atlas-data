# 0037: Binary replay, bounded checkpoints, and immutable ingestion revisions

Status: Proposed for protected review
Date: 2026-09-24
Decision owner: Atlas data stewardship and engineering
Story: #426; prerequisite for #198

## Context

The canonical simplified-ingestion path persisted acquired payloads and complete
normalized results as single JSON/VARIANT checkpoints. Its V069 row MERGEs also
updated prior run lineage on a matching logical record. Large scientific binary
artifacts and revised source snapshots cannot use those behaviors safely.

## Decision

Keep one `IngestionOrchestrator`, one `SourceDefinition`, and the existing CLI.
An adapter may optionally implement `normalize_iter` and yield normalized rows.
The existing `normalize` list method remains the compatibility path for current
JSON, CSV, and XLSX adapters.

For a binary `AcquireResult.payload`, retain the original bytes with the existing
artifact effects. The local file store writes a `.artifact.bin` and SHA-256
metadata; the Snowflake path uses the already governed private Spaces object and
`GOVERNANCE.RAW_ARTIFACTS` ledger. Replay verifies the full SHA-256 before handing
bytes back to the adapter. The binary itself never enters a JSON checkpoint.
Each capture has its own run-scoped artifact ID and request; the full content
SHA-256 identifies byte-identical content across captures. The ACQUIRE checkpoint
retains source/version context and available source metadata.

Streaming normalization writes deterministic partitions of at most 250 rows and
900,000 canonical JSON bytes. A single row over the byte limit fails closed.
Partitions are ordered by the adapter's deterministic iteration order; each has
a zero-based ordinal and SHA-256 over canonical row JSON. Its ID is the ordinal
plus hash within the run. A retry of the same ordinal and content is idempotent;
a different hash at the same ordinal fails. A completion receipt is written only
after a contiguous replayable set exists and a bounded disk-backed identity
index rejects duplicate logical records across partitions. A process failure before or between
partitions leaves the NORMALIZE stage failed and the existing partitions intact.
On resume the source-faithful artifact is replayed; committed partitions are
verified and remaining partitions are appended. If completion was already
recorded, materialization continues from the retained partitions. LOAD repeats
bounded partition effects idempotently. QUALITY aggregates all partitions in
one bounded pass before writing one run-level result. PUBLISH_STAGE records the
count only after earlier stages complete. Existing run-stage status remains the
aggregate operator status.

V103 adds two checkpoint tables and one physical source-record revision ledger.
It changes no existing table or historical row. The first V069 RAW/STAGING/
CONFORMED projection is now insert-only; a matching `record_id` never updates
its original run or value. The revision ledger records each distinct combination
of logical `record_id`, source artifact content SHA-256, source-row hash,
normalized payload hash, and transformation version,
with the original run, artifact, value, source metadata, and retrieval time.
Its `record_revision` is the physical record revision reference used by #193.
An unchanged artifact and row yields the same physical revision; a changed
artifact produces a new immutable physical revision even if the row value is
unchanged. A changed row value produces a new physical revision and preserves
the prior one. This ledger supplies physical inputs for #190 observation keys
and revisions and #193 lineage envelopes; it does not claim that its physical
revision hash is a semantic `revision:v1` ID or authorize publication. Selecting
a current semantic revision remains a governed downstream decision.

## Consequences and limits

Partitioning bounds normalization/checkpoint documents and stage-effect batches.
The acquired binary may still be held as one byte string by an adapter; this
decision does not add a distributed reader or external service. Adapters must
provide deterministic row order and source-native semantics. The generic
quality-rule vocabulary is evaluated in one pass for the streaming path. Existing
legacy V070 JSON checkpoints remain readable. V103 is additive and is not
executed in PROD by this story. No nClimGrid parsing, county aggregation,
public API, or ML feature logic is introduced.

## Alternatives considered

Encoding binary bytes or all normalized rows in one VARIANT was rejected because
it defeats replay and document bounds. A source-specific pipeline or new object
store was rejected because the existing Spaces artifact boundary and canonical
orchestrator suffice. Updating V069 lineage fields was rejected because it
erases historical provenance.

## Acceptance and rollout

Fixture tests cover byte identity, corruption, partition identity and bounds,
partial resume, retries, duplicate protection, and legacy adapters. Query-shape
tests cover additive Snowflake storage; protected DEV migration and runtime
evidence are separate from fixture evidence. PROD promotion still requires ADR
0006 controls and human review. Rollback stops new runs and preserves V103
receipts and immutable revisions; it does not rewrite historical V069 rows.

## Links

- Workspace ADR 0005; data ADR 0027
- `docs/contracts/simplified-ingestion/interface-freeze.md`
- `docs/contracts/semantic-domain/atlas-semantic-domain-v1.md`
- `docs/contracts/semantic-domain/atlas-semantic-lineage-v1.md`
- `migrations/V103__bounded_ingestion_partitions_and_revisions.sql`
- `tests/test_binary_partitioned_ingestion.py`
