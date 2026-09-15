# Pipeline Simplification Phase 2 inventory

Parent: [Epic #259](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/259)
and [Story #253](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/253).

This is the implementation inventory for the Phase 2 backlog. It separates the
routine SourceDefinition path from retained, explicitly governed exception
paths. A retained exception is not a second routine happy path.

## Source and workflow disposition

| Surface | Phase 2 disposition | Canonical evidence or command |
|---|---|---|
| CDC `x5j9-wybp` | Generic Socrata SourceDefinition, live bounded paging, artifact registration, generic RAW/STAGING/CONFORMED projection, quality, and staged publication | `source validate`, then `source run --tier B`; `runs show|explain|resume` |
| CDC `qtbi-xd4i` | Migrated to the same generic Socrata contract with explicit 2008–2021 normalization and value-state preservation | `config/sources/cdc_qtbi_xd4i.yml`; Tier B DEV only for the routine generic path |
| CDC x5j9 legacy capture/approved-ingestion workflows | Unsupported for the normal path and fail closed with a redirect | `.github/workflows/capture-prod-cdc-evidence.yml`, `run-prod-approved-ingestion.yml` |
| Historical CDC protected workflows | Retained only for separately approved historical evidence, publication, recovery, and rollback; they do not authorize routine onboarding | `capture-*-cdc-historical.yml`, `ingest-*-cdc-historical.yml`, recovery and rollback ADRs |
| Tick county-status workbook | Permanent Tier D restricted-egress exception; no generic live Tier B/C acquisition | [ADR 0023](../adr/0023-dev-operator-captured-restricted-evidence.md) and the operator envelope |
| Literature / KG | Durable Snowflake work-item and stage ledgers remain the runtime queue; model, licensing, semantic, and graph-publication decisions remain governed review points | `PMCExtractionWorker`, V068 literature tables, append-only attempt ledger |

## Story mapping

### #254 — migrate qtbi

`qtbi-xd4i` is now a versioned `SourceDefinition` (`definition_version: 2`)
using the shared Socrata adapter and orchestrator. Historical semantics are
explicit: 2008–2021 surveillance era, county of residence, annual surveillance
year, no invented demographic natural key, and preserved source value states.

The existing historical PROD capture/ingestion/recovery workflows remain a
protected exception because they operate on steward-approved source versions,
retained source-faithful snapshots, and publication/rollback controls. They are
not the routine DEV command and must not be copied for another source.

### #255 — canonical LOAD and cutover

The shared runtime owns the generic LOAD boundary. The `run-ingestion.yml`
workflow no longer forces `--dry-run`; Tier B runs execute in the `dev`
environment and persist checkpoints in Snowflake V068. The old x5j9 capture and
approved-ingestion workflows fail closed. The protected historical command is
the only retained source-specific load exception, and it is bounded to an
approved historical source version. New generic Tier C execution uses
`run-prod-ingestion.yml`, which requires an exact reviewed commit, the protected
`production` environment, the dedicated PROD runtime identity, and the same
orchestrator entry point; the public DEV worker continues to reject Tier C.

Every generic row is idempotent by a deterministic record identifier and keeps
the source row hash, source identity, definition version, ingestion run, and
normalized payload. The source-faithful artifact remains immutable in the
private object store and is recorded in the governance artifact ledger.

### #256 — tick envelope

The tick county-status workbook remains Tier D. Its publisher terms, embedded
data-use agreement, restricted workbook handling, and absence semantics require
the operator envelope in [ADR 0023](../adr/0023-dev-operator-captured-restricted-evidence.md).
The generic orchestrator rejects an evidence-only definition for Tier B/C, so
the source cannot accidentally become a routine public-source load.

Revisit trigger and exit criteria: the publisher supplies a permitted row-level
API or an approved runtime-accessible transport; a new source definition and
canonical mapping are reviewed; raw bytes remain private; and the steward
approves the replacement path. Until then, the envelope is permanent Tier D.

### #257 — literature audit

The runtime queue is durable in Snowflake and claims only approved,
provenance-complete OA papers. JATS acquisition, extraction attempts, provider
failures, VPC routing, append-only recovery, and graph receipts remain ledgered.
There is no manual technical unlock between those stages. Human review remains
for licensing ambiguity, semantic admission, partial-acceptance judgment, and
public graph publication; this is a genuine governance decision, not a retry
ceremony.

### API inventory (design only)

The Phase 2 API inventory is a mapping exercise, not authorization to onboard or
cut over a source:

1. CDC x5j9 county Lyme observations — generic Socrata source and county/year
   provenance.
2. CDC tick county status — Tier D workbook evidence only.
3. CDC tick pathogen observations — not represented by the county-status
   workbook; requires a separately reviewed `PATHOGEN_TESTING` source.
4. SVI and RUCC contextual measures — separate source definitions, geography
   versioning, and join semantics are still required.
5. County geometry — separate geometry contract and release/version mapping are
   required.

No API endpoint, web client, source registry, or public mapping is changed by
this inventory.
