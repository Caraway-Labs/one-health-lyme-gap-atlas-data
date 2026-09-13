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
- Payload and normalized projections are persisted with the checkpoint store,
  so a fresh process resumes from the failed stage without reacquiring or
  recomputing completed work.
- `onboarding_mode: EVIDENCE_ONLY` is a fail-closed Tier D marker. It cannot be
  used for a Tier B/C run; the tick operator envelope remains governed by ADR
  0023.

## Local vs DEV

Same orchestrator code. Tier A uses fixture adapters and in-memory/file
checkpoint store. Tier B uses Snowflake checkpoint and stage-effect stores with
live adapters. Tier C is entered only through protected promotion/publication
controls; Tier D uses its separately governed evidence path.
