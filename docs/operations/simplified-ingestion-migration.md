# Epic #223 migration notes for golden-path sources

## Migrated sources

| Source | Adapter | Legacy path status |
|---|---|---|
| `cdc_lyme_x5j9_wybp` | socrata | Source-specific PROD capture/ingest workflows deprecated; use `run-ingestion.yml` + `atlas-data source|runs` |
| `cdc_tick_ixodes_county_status` | http_xlsx | Uses shared orchestrator + fixtures; no new Actions/role/procedure |

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

## Parity checklist (x5j9)

- [x] SourceDefinition loads from existing YAML profile
- [x] Fixture-backed acquire/validate/normalize/load/quality/stage
- [x] Injected failure after ACQUIRE resumes without re-acquiring
- [x] Legacy capture/ingest workflows fail closed with redirect message
- [ ] Live Tier B Snowflake load against DEV (operator-executed with PAT)
- [ ] PROD Tier C via protected promote (unchanged ADR 0006)

## Irreducible source-specific behavior

- Tick workbook sheet/header/byte bounds remain in SourceDefinition + normalize hooks
- CDC quality rule IDs remain source-declared, not orchestrator-branched
