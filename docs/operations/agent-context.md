# Agent context index

Use this short index before governed data work. It is portable: every required
data-repository reference resolves from an isolated checkout. A workspace adds,
but does not replace, the two workspace references below.

| Reference | Classification | When it is authoritative |
| --- | --- | --- |
| `AGENTS.md` | normative entry point | Every data-repository task |
| `README.md` | current product/operation overview | First orientation only |
| `docs/contracts/catalog-to-snowflake/operating-model.md` | executable operating contract | Ingestion or source work |
| `docs/contracts/simplified-ingestion/interface-freeze.md` | executable interface contract | Source/runtime work |
| `docs/operations/connection-inventory.md` | normative connection mapping | Any `snow` inspection |
| `docs/operations/operation-capabilities-v1.md` | versioned curated capability contract | Covered preflight plan |
| `docs/adr/0030-snowflake-role-model-simplification.md` | accepted access-control decision | Identity/privilege questions |
| `migrations/` and `src/lyme_gap_atlas_data/migrations.py` | executable migration/checksum truth | Migration dependencies |
| `docs/contracts/semantic-release/` | executable release manifest contract | Semantic build/release |
| `../AGENTS.md`, `../TECHNOLOGY_AND_GOVERNANCE.md` | workspace normative policy | Assembled workspace only |

## Safe starting sequence

1. Read this index, `AGENTS.md`, and the task's matching contract/ADR.
2. Run `uv run python scripts/check_agent_context.py`; add `--workspace ..`
   only when the assembled workspace is present.
3. For a covered database-affecting plan, run
   `uv run atlas-data pipeline preflight --operation <operation> --environment dev|prod`.
   It is non-mutating. `UNKNOWN` is not absence: obtain separately authorized,
   bounded evidence before the consequential operation.

The four covered operations are `forward_migration`, `governed_source_run`,
`semantic_release`, and `api_read`. The command produces identity, object,
migration, and approval requirements; it never authorizes a mutation.

## Explicit unknowns

This repository cannot prove current live grants, protected-workflow approval,
or deployed artifact state from static files. Those facts require bounded,
authorized observation and remain `UNKNOWN` until observed.
