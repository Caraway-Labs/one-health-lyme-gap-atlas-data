# DEV Snowflake role inventory (Epic #294, Story #295)

Captured 2026-09-16 via read-only `SHOW GRANTS TO ROLE` / `SHOW GRANTS OF ROLE`
against `ONE_HEALTH_LYME_GAP_ATLAS_DEV` using the `BVB26657_PAT` connection.
No role, grant, or user was created, altered, or dropped to produce this
inventory. `BVB26657_PAT` currently resolves to `ACCOUNTADMIN` rather than a
scoped role — see [connection-inventory.md](connection-inventory.md) for why
that connection, and not a lower-privilege one, was necessary to see every
role's grants, and for the fix tracked under Story #300.

11 custom DEV roles exist today (excludes the 2 legacy Alpha POC roles, which
are inventoried in [role-inventory-prod.md](role-inventory-prod.md) alongside
PROD for convenience since they live in the same account).

## OH_LYME_DEV_PIPELINE_RUNTIME

- Total grants: 167. Dominant: `SELECT`/`INSERT`/`UPDATE` on `RAW`/`STAGING`/`CONFORMED`/`GOVERNANCE` tables (136 combined), `USAGE` on 8 schemas, `USAGE` on 3 owner-rights procedures, `OWNERSHIP` on 5 `CONFORMED` views, `READ`/`WRITE` on the ingestion transient stage.
- Holders: `OH_LYME_DEV_PIPELINE_SVC` (USER) — the scheduled ingestion service identity only.
- Role: the scheduled ingestion/dbt-transform runtime. Never holds an owner-rights procedure directly beyond `USAGE`.

## OH_LYME_DEV_STREAMLIT_OWNER

- Total grants: 59. `OWNERSHIP` on 2 Streamlit apps + their internal stages, `OWNERSHIP` on 4 approval views, `USAGE` on 3 owner-rights procedures (including `SP_RECORD_SOURCE_REVIEW_DECISION`), broad `SELECT` across governance tables/views for the explorer UI.
- Holders: `MATTHEWCARAWAY` (USER, interactive Streamlit deploy), `OH_LYME_DEV_SECURITY_ADMIN` (ROLE), `OH_LYME_DEV_STREAMLIT_DEPLOY_SVC` (USER).
- Role: Tier D steward-decision owner-rights role (ADR 0005/0027). Deploys and owns the Streamlit approval console.

## OH_LYME_DEV_GOVERNED_VIEW_OWNER

- Total grants: 22. `OWNERSHIP` on 5 governed/explorer views, `SELECT` on 8 tables + 2 views, `CREATE VIEW` on `GOVERNANCE`.
- Holders: `OH_LYME_DEV_MIGRATION_DEPLOY_SVC` (USER) only.
- Role: narrow owner-rights role scoped to "bounded V041 governed validation and explorer views only" per its Snowflake comment. Only the migration deployer currently holds it — it is never separately assumed by a human or the pipeline runtime.

## OH_LYME_DEV_API_RUNTIME

- Total grants: 12. `SELECT` on the 3 Alpha POC `PRESENTATION` views, `USAGE` on 2 databases, `USAGE` on 5 KG conversation/retrieval procedures.
- Holders: **none.** `SHOW GRANTS OF ROLE` returns zero rows — no user or role currently holds this role.
- Role: provisioned ahead of the Python API's cutover to the governed release (Epic #252 story #275, not yet done). Dormant, not dead — do not delete without confirming #275's status.

## OH_LYME_DEV_KG_PAPER_REVIEW_OWNER

- Total grants: 15. `OWNERSHIP` on 2 recovery procedures, `INSERT`/`SELECT`/`UPDATE` on paper/review tables, `USAGE` on 2 reopen procedures.
- Holders: `MATTHEWCARAWAY` (USER) only.
- Role: literature/KG steward-decision owner-rights role, parallel to `STREAMLIT_OWNER` but for the PubMed/PMC work queue.

## OH_LYME_DEV_KG_LLM_BUDGET_OWNER

- Total grants: 11. `OWNERSHIP` on 2 budget procedures, `INSERT`/`SELECT` on budget tables, `CREATE PROCEDURE` on `GOVERNANCE`.
- Holders: `OH_LYME_DEV_MIGRATION_DEPLOY_SVC` (USER) only.
- Role: narrow owner-rights role for the LLM budget reservation/finalization procedure pair. Same holder as `GOVERNED_VIEW_OWNER` — both are only ever assumed by the migration deployer for `CREATE OR REPLACE ... COPY CURRENT GRANTS`, never by a human or the runtime.

## OH_LYME_DEV_PMC_AUDITOR

- Total grants: 16. Read-only: `SELECT` on 11 tables (budget usage, migrations, extraction attempts), `USAGE` on 1 procedure, 2 schemas, 1 warehouse.
- Holders: `MATTHEWCARAWAY` (USER) only, via the `ATLAS_DEV_PMC_AUDIT` named connection.
- Role: deliberately read-only recovery/audit role for PMC extraction diagnostics.

## OH_LYME_DEV_DATA_STEWARD

- Total grants: 3 — `SELECT` on `V_DISCOVERY_CANDIDATES`, `USAGE` on 2 Streamlit apps.
- Holders: `MATTHEWCARAWAY` (USER).
- **Zero references anywhere in the git-tracked repository** (no migration, no source file, no doc mentions it). It was created directly against the account, not through a committed migration.
- Grants are **byte-for-byte identical** to `OH_LYME_DEV_APPROVAL_VIEWER` below.

## OH_LYME_DEV_APPROVAL_VIEWER

- Total grants: 3 — identical to `OH_LYME_DEV_DATA_STEWARD` (`SELECT` on `V_DISCOVERY_CANDIDATES`, `USAGE` on 2 Streamlit apps).
- Holders: **none.**
- **Zero references anywhere in the git-tracked repository.** Not held by anyone and functionally a duplicate of `DATA_STEWARD`. Strongest deletion candidate in the entire inventory.

## OH_LYME_DEV_MIGRATION_DEPLOYER

- Total grants: 68. `OWNERSHIP` on 30 tables, 11 views, 5 procedures; `CREATE TABLE`/`CREATE VIEW`/`CREATE PROCEDURE` on schemas; `USAGE ON ROLE OH_LYME_DEV_SECURITY_ADMIN`.
- Holders: `OH_LYME_DEV_MIGRATION_DEPLOY_SVC` (USER) only.
- Role: the one-time/per-deploy schema-migration identity. Owns nearly everything created by a forward-only migration, then hands narrow ownership to `GOVERNED_VIEW_OWNER`/`KG_LLM_BUDGET_OWNER` via `COPY CURRENT GRANTS` where a permanent owner-rights procedure boundary is required.

## OH_LYME_DEV_SECURITY_ADMIN

- Total grants: 1 — `USAGE ON ROLE OH_LYME_DEV_STREAMLIT_OWNER`.
- Holders: `MATTHEWCARAWAY` (USER), `OH_LYME_DEV_MIGRATION_DEPLOYER` (ROLE).
- **Zero references anywhere in the git-tracked repository.** Created directly against the account. Its only purpose today is letting the migration deployer assume `STREAMLIT_OWNER` for Streamlit app deploys — a single `GRANT USAGE ON ROLE OH_LYME_DEV_STREAMLIT_OWNER TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER` would achieve the same effect without this extra role existing at all.

## Summary

| Classification | Roles |
|---|---|
| Active, load-bearing | `PIPELINE_RUNTIME`, `STREAMLIT_OWNER`, `GOVERNED_VIEW_OWNER`, `KG_PAPER_REVIEW_OWNER`, `KG_LLM_BUDGET_OWNER`, `PMC_AUDITOR`, `MIGRATION_DEPLOYER` (7) |
| Dormant / reserved for future work, not dead | `API_RUNTIME` (1) |
| Undocumented indirection, no git history, single-purpose | `SECURITY_ADMIN` (1) |
| Unused duplicate, zero references, zero or one accidental holder | `DATA_STEWARD`, `APPROVAL_VIEWER` (2) |

11 total DEV roles: 7 clearly load-bearing, 1 dormant-but-legitimate, 1
undocumented single-purpose indirection, 2 unused duplicates.
