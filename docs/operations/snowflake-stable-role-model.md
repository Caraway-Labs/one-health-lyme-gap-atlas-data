# Stable Snowflake role model (Epic #223 / Story #229; consolidated by Epic #294 / ADR 0030)

## Current model (as of Story #297, DEV; Story #298 mirrors this to PROD)

[ADR 0030](../adr/0030-snowflake-role-model-simplification.md) consolidated
the drifted 11-DEV/9-PROD role inventory documented in
[role-inventory-dev.md](role-inventory-dev.md) and
[role-inventory-prod.md](role-inventory-prod.md) into 5 roles per environment:

| Role | Capability | Notes |
|---|---|---|
| `OH_LYME_{ENV}_RUNTIME` | Ingestion + dbt transform runtime | Renamed from `PIPELINE_RUNTIME`; grants unchanged. Never holds an owner-rights grant beyond `USAGE`. |
| `OH_LYME_{ENV}_OWNER` | Owner-rights: Tier D source and literature steward decisions, governed/explorer views, budget procedures | Merges `GOVERNED_VIEW_OWNER`, `KG_PAPER_REVIEW_OWNER`, and (DEV only) `KG_LLM_BUDGET_OWNER`. Holds `OH_LYME_{ENV}_STREAMLIT_OWNER` via role membership (see below) rather than owning Streamlit objects directly. |
| `OH_LYME_{ENV}_STREAMLIT_OWNER` | Owns the 2 Streamlit apps and their internal stages | **Retained as its own role**, not merged, because Snowflake does not support `GRANT`/`REVOKE OWNERSHIP ON STREAMLIT`. `OH_LYME_{ENV}_OWNER` is granted this role (role-hierarchy nesting) so a session using `OWNER` still has full effective access; the object's registered owner in `SHOW GRANTS`/Streamlit metadata remains this role. |
| `OH_LYME_{ENV}_READ` | Read-only: PMC/KG recovery audit, reserved API-read boundary | Merges `PMC_AUDITOR` and the (dormant, zero-holder) `API_RUNTIME` grants. Both were already read-only. |
| `OH_LYME_{ENV}_MIGRATION_DEPLOYER` | Schema DDL / one-time deploy identity | Unchanged. Now also holds `OH_LYME_{ENV}_OWNER` directly (replacing the removed `SECURITY_ADMIN` indirection role, whose only purpose was `USAGE ON ROLE {ENV}_STREAMLIT_OWNER`). |

Removed entirely (no successor object, zero functional loss):
`OH_LYME_{ENV}_DATA_STEWARD`, `OH_LYME_{ENV}_APPROVAL_VIEWER` (unused
duplicates, zero git references), `OH_LYME_{ENV}_SECURITY_ADMIN`
(undocumented indirection, replaced by a direct role grant).

Net: 11 DEV roles -> 5; 9 PROD roles -> 5 (once Story #298 mirrors this to
PROD). The 2 legacy Alpha POC roles (`OH_LYME_API_READER`,
`OH_LYME_DATA_LOADER`) are unaffected and out of scope.

## Retained invariants (unchanged by this consolidation)

- Ingestion runtime never holds an owner-rights grant beyond `USAGE` — the
  scheduled job can never call `SP_RECORD_SOURCE_REVIEW_DECISION` or
  `SP_RECORD_PAPER_REVIEW_BATCH`.
- Owner-rights procedures remain separated from the runtime role.
- DEV and PROD roles, credentials, and warehouses remain fully independent
  (ADR 0006).
- The migration/deployment identity remains distinct from the routine
  scheduled runtime.

## Goal (unchanged from Epic #223)

Routine public-source onboarding must not create a new Snowflake role or a
source-specific owner procedure solely for orchestration.

## Generic objects (prefer these)

- `GOVERNANCE.INGESTION_RUNS`
- `GOVERNANCE.INGESTION_RUN_CHECKPOINTS` (V068)
- `GOVERNANCE.LITERATURE_WORK_ITEMS` / `LITERATURE_WORK_STAGES` (V068)
- Generic owner-rights procedures for review/reopen — not per-source clones

## Forbidden for routine onboarding

- New `OH_LYME_*_<SOURCE>_*` roles
- New source-specific orchestration-only procedures
- Rewriting approval allowlists solely to unlock Tier B technical stages

## Historical migrations reference the pre-consolidation role names

Migrations `V041`-`V073` are checksum-locked and immutable; several
reference `OH_LYME_DEV_STREAMLIT_OWNER`, `OH_LYME_DEV_GOVERNED_VIEW_OWNER`,
`OH_LYME_DEV_KG_PAPER_REVIEW_OWNER`, `OH_LYME_DEV_KG_LLM_BUDGET_OWNER`, or
`OH_LYME_DEV_PIPELINE_RUNTIME` by their pre-consolidation names in their
literal SQL text and in `migration_execution_role()`'s historical-version
mapping in `src/lyme_gap_atlas_data/migrations.py`. Their source checksums must
never change.

The live DEV ledger had applied V001-V070 when role consolidation retired the
legacy names, leaving V071-V073 pending. For those three pending semantic-release
migrations only, the runner renders the retired identifiers to their accepted
ADR 0030 successors at execution time: `GOVERNED_VIEW_OWNER` to `OWNER`,
`PIPELINE_RUNTIME` to `RUNTIME`, and `API_RUNTIME` to `READ`. V072 also runs
under `OWNER`. The stored migration files and ledger checksums remain unchanged;
this narrowly bridges the live transition without recreating a retired role or
granting owner rights to the routine runtime. All other historical migration
role mappings remain literal and are not a replay mechanism for a new database.

## Privilege-contract tests

See `tests/test_snowflake_role_model.py`.
