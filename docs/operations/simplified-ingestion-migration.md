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
the protected promotion/publication workflows; evidence-only definitions are
also rejected for Tier B/C.

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
