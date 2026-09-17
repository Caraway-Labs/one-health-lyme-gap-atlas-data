# PROD (and legacy Alpha POC) Snowflake role inventory (Epic #294, Story #295)

Captured 2026-09-16 via read-only `SHOW GRANTS TO ROLE` / `SHOW GRANTS OF ROLE`
against `ONE_HEALTH_LYME_GAP_ATLAS_PROD` and the legacy
`ONE_HEALTH_LYME_GAP_ATLAS` (Alpha POC) database, using the `BVB26657_PAT`
connection (see [connection-inventory.md](connection-inventory.md) for why an
`ACCOUNTADMIN`-resolving connection was needed and the plan to fix that under
Story #300). No role, grant, or user was created, altered, or dropped to
produce this inventory. The Alpha POC roles are out of scope for role-model
changes under this epic (`AGENTS.md`); they are inventoried here only for
completeness.

## OH_LYME_PROD_PIPELINE_RUNTIME

- Total grants: 131 — same shape as its DEV counterpart (`SELECT`/`INSERT`/`UPDATE` on `RAW`/`STAGING`/`CONFORMED`/`GOVERNANCE`, ownership of 4 `CONFORMED` views, transient-stage read/write).
- Holders: `MATTHEWCARAWAY` (USER, via the `ATLAS_PROD_RUNTIME_AUDIT` read-only audit connection) and `OH_LYME_PROD_PIPELINE_SVC` (USER, the scheduled job).
- Active, load-bearing.

## OH_LYME_PROD_STREAMLIT_OWNER

- Total grants: 53 — same shape as DEV (owns 2 Streamlit apps + stages, 1 owner-rights procedure, broad governance `SELECT`).
- Holders: `MATTHEWCARAWAY` (USER), `OH_LYME_PROD_SECURITY_ADMIN` (ROLE).
- Active, load-bearing.

## OH_LYME_PROD_GOVERNED_VIEW_OWNER

- Total grants: 41 — `OWNERSHIP` on 13 views, `SELECT` on 17 tables + 2 views, `CREATE VIEW` on `GOVERNANCE`/`PRESENTATION`.
- Holders: `ACCOUNTADMIN` (ROLE), `OH_LYME_PROD_MIGRATION_DEPLOY_SVC` (USER).
- Active, load-bearing. Broader than its DEV counterpart because it now also owns `PRESENTATION.SEMANTIC_RELEASE_STATUS_V` (Epic #252 semantic release).

## OH_LYME_PROD_API_RUNTIME

- Total grants: 16 — `SELECT` on the 6 Alpha POC `PRESENTATION` views, `USAGE` on 2 databases, `USAGE` on 5 KG procedures.
- Holders: **none.**
- Dormant, reserved for the API cutover (Epic #252 story #275), same as its DEV counterpart. Do not delete without confirming that story's status.

## OH_LYME_PROD_KG_PAPER_REVIEW_OWNER

- Total grants: 10 — `OWNERSHIP` on 1 procedure, `INSERT`/`SELECT`/`UPDATE` on paper/review tables.
- Holders: **none.**
- Dormant, reserved for a future PROD literature/KG activation (the literature pipeline is DEV-only today per `docs/operations/simplified-ingestion-migration.md`).

## OH_LYME_PROD_DATA_STEWARD

- Total grants: 3 — identical shape to DEV (`SELECT` on `V_DISCOVERY_CANDIDATES`, `USAGE` on 2 Streamlit apps).
- Holders: `MATTHEWCARAWAY` (USER).
- Zero references in the git-tracked repository. Identical grants to `OH_LYME_PROD_APPROVAL_VIEWER`.

## OH_LYME_PROD_APPROVAL_VIEWER

- Total grants: 3 — identical to `OH_LYME_PROD_DATA_STEWARD`.
- Holders: **none.**
- Zero references in the git-tracked repository. Strongest deletion candidate, same pattern as DEV.

## OH_LYME_PROD_MIGRATION_DEPLOYER

- Total grants: 19 — `OWNERSHIP` on 6 tables, `CREATE TABLE` on 4 schemas, `SELECT` on 2 migration-ledger tables.
- Holders: `OH_LYME_PROD_MIGRATION_DEPLOY_SVC` (USER) only.
- Active, load-bearing. Notably smaller footprint than DEV's migration deployer (19 vs. 68 grants) because most PROD ownership routes through `GOVERNED_VIEW_OWNER` instead.

## OH_LYME_PROD_SECURITY_ADMIN

- Total grants: 1 — `USAGE ON ROLE OH_LYME_PROD_STREAMLIT_OWNER`.
- Holders: **none.** Unlike its DEV counterpart (held by a human and the migration deployer), nobody currently holds `OH_LYME_PROD_SECURITY_ADMIN` at all — it is completely disconnected from any principal today.
- Zero references in the git-tracked repository. Even weaker justification for existing than `OH_LYME_DEV_SECURITY_ADMIN`.

## Legacy Alpha POC roles (out of scope for this epic's role-model change, inventoried for completeness)

### OH_LYME_API_READER

- Total grants: 20 — `SELECT` on the 3 Alpha `PRESENTATION` views, plus grants that were layered on later for KG conversation procedures shared across environments.
- Holders: `OH_LYME_API_SVC` (USER) — this is the role the current production API actually authenticates as today.

### OH_LYME_DATA_LOADER

- Total grants: 16 — `DELETE`/`INSERT`/`SELECT`/`UPDATE` on the 3 `LANDING` tables, `USAGE` on `LANDING`/`PRESENTATION`.
- Holders: **none.** Defined in `sql/002_security_admin.sql` for one-time/occasional manual Alpha POC loads; nobody is currently granted it, consistent with it being an occasional manual-assumption role rather than a persistent identity.

## Summary

| Classification | Roles |
|---|---|
| Active, load-bearing | `PIPELINE_RUNTIME`, `STREAMLIT_OWNER`, `GOVERNED_VIEW_OWNER`, `MIGRATION_DEPLOYER` (4) |
| Dormant / reserved for future work, not dead | `API_RUNTIME`, `KG_PAPER_REVIEW_OWNER` (2) |
| Undocumented indirection, no git history, zero holders | `SECURITY_ADMIN` (1) |
| Unused duplicate, zero references, at most one accidental holder | `DATA_STEWARD`, `APPROVAL_VIEWER` (2) |

9 total PROD custom roles: 4 clearly load-bearing, 2 dormant-but-legitimate, 1
undocumented and currently unheld, 2 unused duplicates — the same shape as
DEV, confirming the sprawl pattern is systemic rather than one-off.
