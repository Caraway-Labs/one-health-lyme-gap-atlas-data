# Epic #259 migration notes for simplified ingestion

## Migrated sources

| Source | Adapter | Legacy path status |
|---|---|---|
| `cdc_lyme_x5j9_wybp` | socrata | Source-specific PROD capture/ingest workflows deprecated; use `run-ingestion.yml` + `atlas-data source|runs` |
| `cdc_lyme_qtbi_xd4i` | socrata | Migrated to the shared live DEV path; protected historical workflows remain exception-only |
| `cdc_tick_ixodes_county_status` | http_xlsx | Tier D restricted-egress envelope remains; fixtures exercise schema/normalization only |

## Canonical commands

```bash
uv run atlas-data source validate --definition config/sources/cdc_x5j9_wybp.yml
uv run atlas-data source run --definition config/sources/cdc_x5j9_wybp.yml --tier A
uv run atlas-data source dev-smoke
uv run atlas-data runs list
uv run atlas-data runs show --run-id <id>
uv run atlas-data runs explain --run-id <id>
uv run atlas-data runs resume --run-id <id> --definition config/sources/cdc_x5j9_wybp.yml
```

For a live routine public source, use `--tier B` in the isolated DEV
environment. The command persists payloads, stage checkpoints, and generic
load/quality/publication effects. Tier C is rejected by the CLI and belongs to
the protected `run-prod-ingestion.yml` workflow, which invokes the same CLI
with the production environment guard and `--tier C`; evidence-only definitions
are also rejected for Tier B/C. The protected workflow requires the exact
reviewed commit and verifies the dedicated PROD runtime identity before any
acquisition or warehouse write.

### DEV runtime identity and artifact storage

`run-ingestion.yml` is a worker operation, not a migration operation. In the
`dev` GitHub Environment it must use the dedicated runtime service principal
and the role already assigned to that principal:

| GitHub secret | Required value |
|---|---|
| `SNOWFLAKE_RUNTIME_USER` | `OH_LYME_DEV_PIPELINE_SVC` |
| `SNOWFLAKE_RUNTIME_ROLE` | `OH_LYME_DEV_RUNTIME` |
| `SNOWFLAKE_RUNTIME_PRIVATE_KEY_B64` | Encrypted PKCS#8 PEM body for that service user; do not include PEM headers |
| `SNOWFLAKE_RUNTIME_PRIVATE_KEY_PASSPHRASE` | Passphrase for that key |

Keep the migration-only `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`,
`SNOWFLAKE_PRIVATE_KEY_B64`, and `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` secrets
for `deploy-dev.yml`. The runtime workflow also requires the DEV Spaces
endpoint, bucket, prefix, access key, and secret access key so it can retain
the immutable private acquisition artifact before Snowflake writes. The
workflow verifies the resolved user, role, database, and warehouse before it
starts the orchestrator and fails closed if the migration identity is supplied.

## Parity checklist (x5j9)

- [x] SourceDefinition loads from existing YAML profile
- [x] Fixture-backed acquire/validate/normalize/load/quality/stage
- [x] Injected failure after ACQUIRE resumes without re-acquiring
- [x] Legacy capture/ingest workflows fail closed with redirect message
- [ ] Live Tier B Snowflake load against DEV (protected workflow evidence)
- [ ] PROD Tier C via protected promote (unchanged ADR 0006)

See [the Phase 2 inventory](pipeline-simplification-phase2-inventory.md) and
[the Epic #259 scorecard](epic-259-closeout-scorecard.md) for the full source
and exception disposition.

## Irreducible source-specific behavior

- Tick workbook sheet/header/byte bounds remain in SourceDefinition + normalize hooks
- CDC quality rule IDs remain source-declared, not orchestrator-branched
