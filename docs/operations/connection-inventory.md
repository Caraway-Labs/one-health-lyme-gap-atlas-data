# `snow` CLI connection-surface audit and reconciliation (Epic #294, Stories #295 and #300)

Story #295 captured the pre-consolidation inventory on 2026-09-16 (12 named
connections). Story #300 reconciled the client-side `snow` connection surface
to the role model [ADR 0030](../adr/0030-snowflake-role-model-simplification.md)
accepted and Stories #297/#298 implemented. **No Snowflake role, grant, or
user was created, altered, or dropped by Story #300** beyond the PAT rotation
described below (a client-authorized action, not a governance-scoped
role/grant change); everything else was local `connections.toml` editing and
documentation.

## Final connection surface (10 named connections, down from 12)

| Connection | Role (verified live) | Purpose |
|---|---|---|
| `MM06468` | interactive human | Personal interactive login, second account (out of scope for this epic) |
| `BVB26657` | interactive human | Personal interactive login, primary account |
| `ATLAS_DEV_READ` | `OH_LYME_DEV_READ` (verified live) | **Default for routine agent-initiated DEV read/inspection work** (PMC/migration-ledger audit, general read checks) |
| `ATLAS_DEV_OWNER` | `OH_LYME_DEV_OWNER` (verified live) | DEV owner-rights: Streamlit deploy, governed-view/budget-procedure ownership, literature/paper-review steward decisions |
| `ATLAS_PROD_MIGRATOR` | `OH_LYME_PROD_MIGRATION_DEPLOYER` (verified live) | PROD schema migration deploys |
| `ATLAS_PROD_OWNER` | `OH_LYME_PROD_OWNER` (verified live) | PROD owner-rights: Streamlit deploy (confirmed via `SHOW STREAMLITS` returning both apps through the nested `STREAMLIT_OWNER` role grant), governed-view/budget-procedure ownership, literature/paper-review |
| `ATLAS_PROD_RUNTIME_AUDIT` | `OH_LYME_PROD_RUNTIME` (verified live, unchanged from Story #298) | Read-only PROD runtime audit/verification |
| `BVB26657_PAT` | `ACCOUNTADMIN` (unchanged; verified live in Story #295) | **Reserved, not default.** Only for explicitly authorized administrative/inventory work that genuinely needs `ACCOUNTADMIN` (e.g. a future full `SHOW GRANTS` sweep). No longer the routine agent default — see "Fixed: the over-privileged default" below. |
| `BVB26657_ACCOUNTADMIN_PAT` | presumed `ACCOUNTADMIN` (found expired in Story #295; not re-verified) | One-time DEV account-admin bootstrap actions. Left untouched — expired-PAT rotation for an intentionally exceptional, rarely-used credential is an owner decision, not part of this story's routine-surface scope. |
| `ATLAS_RESUME_MIGRATOR` | `ACCOUNTADMIN` (declared in connection params) | Migration-ledger recovery/resume — intentionally exceptional, left untouched |

## Which connection do I use for X?

| Task | Connection |
|---|---|
| Routine DEV read/inspection (PMC audit, migration-ledger check, general `SELECT`) | `ATLAS_DEV_READ` |
| DEV Streamlit app deploy, governed-view/budget-procedure owner action, literature/paper-review decision | `ATLAS_DEV_OWNER` |
| DEV schema migration | Protected `deploy-dev.yml` workflow (service credential, not a personal `snow` connection) |
| PROD schema migration | `ATLAS_PROD_MIGRATOR` |
| PROD Streamlit app deploy, governed-view/budget-procedure owner action, literature/paper-review decision | `ATLAS_PROD_OWNER` |
| Read-only PROD runtime identity/audit check | `ATLAS_PROD_RUNTIME_AUDIT` |
| Migration-ledger recovery/resume (exceptional) | `ATLAS_RESUME_MIGRATOR` |
| A genuinely account-admin-level one-off (new role/grant bootstrap, cross-role `SHOW GRANTS` sweep) — requires explicit user authorization for that specific action | `BVB26657_PAT` |
| Interactive human login | `BVB26657` (primary) / `MM06468` (secondary account) |

## Retired connections (redundant after role consolidation)

- `BVB26657_STREAMLIT_OWNER_PAT` — retired. `OH_LYME_DEV_OWNER` is granted
  `OH_LYME_DEV_STREAMLIT_OWNER` via role-hierarchy membership (Story #297), so
  a session authenticated as `OWNER` already has full Streamlit deploy access;
  `ATLAS_DEV_OWNER` replaces it.
- `ATLAS_PROD_STREAMLIT_OWNER` — retired for the same reason on the PROD side
  (Story #298's mirrored role grant). Verified live: `ATLAS_PROD_OWNER`'s
  `SHOW STREAMLITS` returns both `GOVERNED_DATA_EXPLORER` and
  `SOURCE_APPROVAL_CONSOLE`.
- `BVB26657_SECURITY_ADMIN_PAT` — retired. `OH_LYME_DEV_SECURITY_ADMIN` was
  dropped in Story #297 (the "eliminate this indirection" finding in
  [role-classification.md](role-classification.md)); the connection's target
  role no longer exists.
- `ATLAS_DEV_PMC_AUDIT` — replaced by `ATLAS_DEV_READ` (same role,
  `OH_LYME_DEV_READ`, renamed to reflect its broadened, non-PMC-specific
  scope; its underlying PAT was invalid after Story #297's role rename and
  needed rotation anyway).
- `ATLAS_DEV_PMC_REVIEW_OWNER` — replaced by `ATLAS_DEV_OWNER` (same role,
  `OH_LYME_DEV_OWNER`, renamed for the same reason).

## Fixed: the over-privileged default

Story #295 found that `AGENTS.md` (workspace and data-repo) named
`BVB26657_PAT` as the default connection for agent-initiated Snowflake work,
despite it resolving to `ACCOUNTADMIN`. Story #300 fixes this at the
documentation level (both `AGENTS.md` files now point to `ATLAS_DEV_READ` as
the default for routine work) and confirmed the fix could not be done by
simply editing `BVB26657_PAT`'s `role` parameter: Snowflake Programmatic
Access Tokens carry an optional `ROLE_RESTRICTION` set at mint time, and this
particular PAT was minted unrestricted (defaulting to the account default
role, `ACCOUNTADMIN`), not restricted to a role that could be swapped
client-side. A client-side `role` override against an unrestricted-but-wrong
default still authenticates as the account default; a `role` override against
a *restricted* PAT for a role other than its restriction fails outright
(confirmed live: `snow sql -c BVB26657_PAT --role OH_LYME_DEV_READ ...` →
"Role ... is not permitted for the credentials being used"). The only fix is
a newly minted, role-restricted PAT — `ATLAS_DEV_READ`, minted with
`ROLE_RESTRICTION = 'OH_LYME_DEV_READ'`.

Note for future PAT rotations: Snowflake refuses to mint a new PAT for a user
while authenticated *as that same user via an existing PAT*
(`099413 (38002): Cannot use a programmatic access token as the
authentication method to modify programmatic access tokens for the same
user`). Combined with `AGENTS.md`'s prohibition on agent-initiated
interactive/OAuth authentication, this means an agent cannot self-service a
future PAT rotation for this account — the account owner must run the
`ALTER USER ... ADD PROGRAMMATIC ACCESS TOKEN ... ROLE_RESTRICTION = '...'`
statement interactively (as happened for this story's four new PATs) and hand
the resulting secret to the agent to wire into `connections.toml`.

`BVB26657_PAT` itself is left pointed at its existing `ACCOUNTADMIN` PAT,
unchanged — it is not deleted, only demoted from "default" to "reserved,
explicitly-authorized-use-only" in both `AGENTS.md` files, so an
already-authorized future admin action (e.g. a full cross-role `SHOW GRANTS`
sweep like Story #295's) still has a working credential without requiring a
fresh mint.

## Scorecard: before / after

| Metric | Before (Story #295) | After (Story #300) |
|---|---|---|
| Named `snow` connections | 12 | 10 |
| Custom Snowflake roles | 22 | 8 (Stories #297/#298, unchanged by this story) |
| Documented agent default resolves to | `ACCOUNTADMIN` | `OH_LYME_DEV_READ` |
| Dead/invalid PATs in `connections.toml` | 2 (`ATLAS_DEV_PMC_AUDIT`, `ATLAS_DEV_PMC_REVIEW_OWNER`, both invalidated by Story #297's role rename) | 0 |
| PROD connections resolving to an unintended default role | 1 (`ATLAS_PROD_MIGRATOR` → `ACCOUNTADMIN` instead of `OH_LYME_PROD_MIGRATION_DEPLOYER`) | 0 |
| Named ADR 0005/0006/0027 controls dropped by this story | n/a | **0** |
