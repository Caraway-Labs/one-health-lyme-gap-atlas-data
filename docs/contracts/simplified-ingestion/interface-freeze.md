# Simplified Ingestion Interface Freeze (Waves 1-2)

Epic #223 / Stories #225, #226, #228. Frozen before parallel implementation.
Do not invent a second orchestration entry point.

## SourceDefinition (minimal for `cdc_lyme_x5j9_wybp`)

Required fields:

- `resource_key` (stable source/dataset identity)
- `source_id` / `dataset_id` (lineage anchors; may default from resource_key)
- `definition_version` (int; maps from `profile_version` for legacy YAML)
- `adapter_kind`: `socrata` | `http_xlsx` (http_xlsx added in Wave 3)
- `endpoint_template`, optional `metadata_endpoint_template`
- `auth_mode`: `none` | `app_token_env`
- `deterministic_order_clause`
- `incremental_strategy`
- `geography_semantics`, `temporal_semantics`
- `license_usage` / `restrictions` (list of strings is acceptable)
- `artifact_policy` (retention class default `PUBLIC_SEVEN_YEAR`)
- `quality_rules` (list of `{rule_id, severity}`)
- `destination` (`raw_table` intent string; physical DDL stays in migrations)
- `cadence` / `expected_refresh_cadence`
- `stages` optional override; default for Socrata golden path:
  `ACQUIRE, VALIDATE, NORMALIZE, LOAD, QUALITY, PUBLISH_STAGE`

Not allowed in SourceDefinition: transformation programs, orchestration
branching, Snowflake role names, #188 Indicator/Measure semantics.

## Stages

```text
DISCOVER | ACQUIRE | VALIDATE | NORMALIZE | LOAD | QUALITY | PUBLISH_STAGE
```

Sources may skip stages. Empty ceremony is forbidden.

## Checkpoint record

Persisted on `GOVERNANCE.INGESTION_RUNS` (extended) and/or
`GOVERNANCE.INGESTION_RUN_CHECKPOINTS`:

- `ingestion_run_id`
- `resource_key`, `source_definition_version`
- `stage`, `status` (`PENDING|RUNNING|COMPLETED|FAILED|SKIPPED`)
- `attempt_count`
- `artifact_id`, `artifact_sha256` (when applicable)
- `transformation_version`
- `failure_category`, `redacted_diagnostic_code`
- `next_action`
- timestamps

## IngestionOrchestrator API

```python
class IngestionOrchestrator:
    def validate(self, definition: SourceDefinition) -> ValidationResult: ...
    def run(
        self,
        definition: SourceDefinition,
        *,
        tier: Tier,
        dry_run: bool = False,
        fail_after_stage: str | None = None,
    ) -> RunState: ...
    def resume(self, run_id: str, *, fail_after_stage: str | None = None) -> RunState: ...
    def inspect(self, run_id: str) -> RunState: ...
```

CLI and GitHub Actions must call this service only.

## Failure categories (skeleton for #231)

`CONFIGURATION | ACQUISITION | POLICY_LICENSE | SCHEMA | NORMALIZATION |
WAREHOUSE | QUALITY | PROVIDER_MODEL | GRAPH | DEPLOYMENT | PERMISSION`

## Fixture layout

```text
tests/fixtures/sources/cdc_lyme_x5j9_wybp/
  definition.yml          # or symlink to config/sources
  metadata.json
  sample.json
  expected_normalized.json
```

## Phase 2 runtime extension

The frozen interface is extended without adding a second orchestration entry
point:

- `page_size` and `maximum_rows` bound live Socrata paging; HTTP/XLSX keeps its
  declared byte and row bounds.
- Live adapters return the retained response bytes and a checksum. A generic
  stage-effects boundary registers the immutable artifact, materializes the
  normalized projection, loads idempotent V069 rows, records quality results,
  and stages publication lineage.
- Payload and normalized projections are persisted with the checkpoint store
  (`GOVERNANCE.INGESTION_RUN_PAYLOADS` and
  `GOVERNANCE.INGESTION_RUN_NORMALIZED`), with checksums verified on write and
  read, so a fresh process resumes from the failed stage without reacquiring
  or recomputing completed work.
- `onboarding_mode: EVIDENCE_ONLY` is a fail-closed Tier D marker. It cannot be
  used for a Tier B/C run; the tick operator envelope remains governed by ADR
  0023.

## Local vs DEV

Same orchestrator code. Tier A uses fixture adapters and in-memory/file
checkpoint store. Tier B uses Snowflake checkpoint and stage-effect stores with
live adapters. Tier C is entered only through protected promotion/publication
controls; Tier D uses its separately governed evidence path.

## Source-row identity and revision policy

For Socrata sources, the adapter requests and retains `:id`, `:created_at`, and
`:updated_at` system fields when the provider exposes them. `source_record_id`
uses the non-empty publisher `:id` (or an explicitly supplied compatibility
`id` field); `record_id` is deterministic over the resource key, definition
version, and that publisher identity. The source-row checksum includes the
complete retained row and is allowed to change when a publisher revision
changes.

If no publisher system ID is present, `source_record_id` remains null and
`record_id` uses the canonical full-row SHA-256. This is a documented identity
limitation, not a natural key inferred from geography, year, case, sex, age, or
other analytical dimensions. See
`x5j9-record-identity-policy.md` for the bounded evidence and revision
decision.

## Story #426 bounded replay extension

ADR 0037 extends this freeze without a new CLI or required adapter migration.
The existing list-returning `normalize` remains supported. A large-source
adapter may provide `normalize_iter`, yielding rows in a documented stable order.
The orchestrator partitions that iterator at 250 rows and 900,000 canonical
JSON bytes, whichever comes first, and never stores the full normalized list.
The storage-neutral partition operations are `save_partition`,
`iter_partitions`, `complete_partitions`, and `partitions_complete`. A partition
is identified within its run by ordinal and content SHA-256. Duplicate content
at the same ordinal is idempotent; different content fails. The completion
receipt requires contiguous ordinals. The existing NORMALIZE stage is complete
only after the receipt and bounded materialization succeed; LOAD, QUALITY and
PUBLISH_STAGE keep their existing run-status semantics.

Binary `AcquireResult.payload` uses source-faithful bytes and a SHA-256 verified
artifact checkpoint. Local storage uses a binary file; Snowflake uses the
existing private Spaces/RAW_ARTIFACTS boundary. No binary value is serialized
into V070 JSON. Source artifact IDs are capture/run scoped; full SHA-256 is the
stable cross-run content identity.

The V069 generic RAW/STAGING/CONFORMED projection MERGE is insert-only as of
V103 deployment. These first-write rows are convenience projections, not the
authoritative run-pinned read model. The additive V103 ledger retains one
immutable capture per run and logical `record_id`, including source record ID,
value, artifact, and retrieval lineage. Identical recapture has its own run
capture but the same content-derived `record_revision`; changed content has a
new revision. Governed generic consumers select
`GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS` by exact `resource_key`,
`ingestion_run_id`, and `source_definition_version`. The semantic release reader
falls back to an exact-run V069 row only for a pre-V103 run without a capture.
This is a physical input to #190/#193 semantic
revision and lineage validation, not a new scientific identity model. Existing
V070 checkpoints and source adapters remain readable and executable.
