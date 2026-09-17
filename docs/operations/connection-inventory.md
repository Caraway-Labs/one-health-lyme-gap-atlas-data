# `snow` CLI connection-surface audit (Epic #294, Story #295)

Captured 2026-09-16 from `snow connection list` (local `connections.toml`) plus
a bounded read-only `SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(),
CURRENT_WAREHOUSE()` per connection. No connection was created, modified, or
removed.

## Inventory

| Connection | Authenticator | Resolved role (verified live) | Purpose |
|---|---|---|---|
| `MM06468` | OAuth (browser) | interactive human | Personal interactive login, second account |
| `BVB26657` | OAuth (browser) | interactive human | Personal interactive login, primary account |
| `BVB26657_PAT` | PAT | **`ACCOUNTADMIN`** (verified live) | Documented in `AGENTS.md` as the default for agent-initiated Snowflake work |
| `BVB26657_STREAMLIT_OWNER_PAT` | PAT | `OH_LYME_DEV_STREAMLIT_OWNER` (verified live) | DEV Streamlit app deploy/owner actions |
| `BVB26657_SECURITY_ADMIN_PAT` | PAT | presumed `OH_LYME_DEV_SECURITY_ADMIN` (name implies; not re-verified live in this pass) | One-time DEV security-admin bootstrap actions |
| `BVB26657_ACCOUNTADMIN_PAT` | PAT | presumed `ACCOUNTADMIN` | One-time DEV account-admin bootstrap actions |
| `ATLAS_PROD_MIGRATOR` | PAT | presumed `OH_LYME_PROD_MIGRATION_DEPLOYER` | PROD schema migration deploys |
| `ATLAS_PROD_STREAMLIT_OWNER` | PAT | presumed `OH_LYME_PROD_STREAMLIT_OWNER` | PROD Streamlit app deploy/owner actions |
| `ATLAS_PROD_RUNTIME_AUDIT` | PAT | `OH_LYME_PROD_PIPELINE_RUNTIME` (verified live) | Read-only PROD runtime audit/verification |
| `ATLAS_RESUME_MIGRATOR` | PAT | `ACCOUNTADMIN` (declared in connection params) | Migration-ledger recovery/resume |
| `ATLAS_DEV_PMC_AUDIT` | PAT | `OH_LYME_DEV_PMC_AUDITOR` (declared) | DEV PMC extraction recovery audit |
| `ATLAS_DEV_PMC_REVIEW_OWNER` | PAT | `OH_LYME_DEV_KG_PAPER_REVIEW_OWNER` (declared) | DEV literature/KG paper-review owner-rights actions |

**12 named connections** (2 interactive + 10 PAT-based) are required today to
operate this one pipeline across its lifecycle: routine ingestion, dbt,
Streamlit deploys, migrations, PMC recovery audit, and one-time bootstrap.

## Key finding: the documented default connection is over-privileged

`AGENTS.md` (workspace and data-repo) names `BVB26657_PAT` as the default
connection for Codex/agent-initiated Snowflake work, with the explicit
instruction to "use a DEV, least-privilege connection by default." Live
verification shows it resolves to `ACCOUNTADMIN`, not a DEV runtime or
governed-read role — the connection's `role` parameter is unset in
`connections.toml`, so it falls back to the user's account default role.

This is a real governance gap independent of this epic's role-count decision:
today, any agent following the documented default for a "quick read-only
check" is actually authenticating as `ACCOUNTADMIN`. It is the reason this
inventory pass itself had to use `BVB26657_PAT` for the full `SHOW GRANTS`
sweep (a scoped role cannot see another role's grants without `MANAGE GRANTS`),
which is a legitimate one-time use — but it should not be the *default* for
routine work. Story #300 fixes this by either setting an explicit low-privilege
`role` on `BVB26657_PAT` or introducing a dedicated `BVB26657_DEV_READONLY`-style
connection and updating `AGENTS.md` to point to it.

## Connections mapped to role classification

Cross-referencing [role-inventory-dev.md](role-inventory-dev.md) and
[role-inventory-prod.md](role-inventory-prod.md):

- Connections exist for every **active, load-bearing** role category except
  `KG_LLM_BUDGET_OWNER` and `GOVERNED_VIEW_OWNER` (both are only ever assumed
  transiently by the migration-deployer connections via `COPY CURRENT GRANTS`,
  never given their own named connection).
- No connection exists for `API_RUNTIME` (DEV or PROD) or
  `PROD_KG_PAPER_REVIEW_OWNER` — consistent with those roles being dormant/
  reserved rather than actively operated today.
- No connection exists for `DATA_STEWARD` or `APPROVAL_VIEWER` (DEV or PROD) —
  consistent with the finding that these four roles are unused duplicates.
- `BVB26657_SECURITY_ADMIN_PAT` and `BVB26657_ACCOUNTADMIN_PAT` are both
  labeled "one-time" by their token file paths
  (`atlas-dev-security-admin-one-time.pat`, `atlas-dev-accountadmin-one-time.pat`),
  meaning even the connection-naming convention already recognizes these as
  exceptional, not routine, identities.

## Implication for the ADR options (Story #296)

Whichever role-count option the product owner picks, the number of *named
connections* a developer/agent must hold is a direct, measurable consequence:

- A true 2-role model (`DEV_ALL`, `PROD_ALL`) would reduce the above to
  roughly 4 connections (1 interactive + 1 DEV PAT + 1 PROD PAT + 1 legacy
  Alpha POC), the largest reduction, at the cost of the separation-of-duties
  controls itemized in [role-classification.md](role-classification.md).
- The ~4-roles-per-environment consolidated option would reduce the above to
  roughly 6-7 connections (runtime, approval/steward, governed-read/API,
  migration/deploy, per environment, plus interactive) while keeping
  "runtime never approves" and "owner-rights separated from runtime" intact.
- Either option can independently retire `BVB26657_SECURITY_ADMIN_PAT`,
  `BVB26657_ACCOUNTADMIN_PAT`, and the standalone `SECURITY_ADMIN` roles per
  the "eliminate this indirection" finding in
  [role-classification.md](role-classification.md), and can delete
  `DATA_STEWARD`/`APPROVAL_VIEWER` in both environments immediately with zero
  functional risk (see that document's "no-regret deletions" section).
