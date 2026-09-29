# Dataset Discovery PROD role bootstrap and grant gate

Accepted [ADR 0041](../adr/0041-dataset-discovery-recommendation-roles.md) requires
three PROD-only roles. The account-level bootstrap is a separately protected
security action because the migration deployer cannot create roles or grant
account `READ SESSION`. Do not execute it from a routine migration connection.

The account owner or delegated security administrator reviews the exact commit,
approves the account-level action, and runs the reviewed
[`bootstrap_dataset_discovery_roles_prod.sql`](../../scripts/bootstrap_dataset_discovery_roles_prod.sql)
with the named `BVB26657_PAT` administrative connection, only after explicit
approval for this exact PROD role/grant action. It resolves to `ACCOUNTADMIN`
per the connection inventory and must never become a routine deploy credential.
Before any Snowflake action, query `CURRENT_USER()`, `CURRENT_ROLE()`,
`CURRENT_DATABASE()`, and `CURRENT_WAREHOUSE()` using that connection. Record
the file SHA, query IDs, and `SHOW GRANTS TO ROLE` / `SHOW GRANTS OF ROLE`
results without credentials. Stop on unexpected existing grants or hierarchy.
The exact approved command is:

```powershell
snow sql -c BVB26657_PAT -q "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()" --format JSON
snow sql -c BVB26657_PAT -f scripts/bootstrap_dataset_discovery_roles_prod.sql
```

The file uses `CREATE ROLE IF NOT EXISTS` and exact repeatable `GRANT`s. It
creates `OH_LYME_PROD_DATASET_DISCOVERY_RUNTIME`, `REVIEWER`, and `WRITE_OWNER`.
Only `WRITE_OWNER` receives account `READ SESSION`, for authenticated caller
attribution in the owner-rights review and handoff procedures. It is a role
with no user login or service credential; the only hierarchy edge is to the
PROD migration deployer for procedure ownership transfer. It receives bounded
database, `GOVERNANCE` schema, catalog table, and procedure dependency access,
not general GOVERNANCE ownership. Runtime/reviewer get database and warehouse
usage; reviewer gets GOVERNANCE schema usage for the exact handoff procedure.
No DEV role or database is named. The file creates no user and assigns no role
to a human or service principal.

After V106–V113 and V123/V124 are eligible, the protected PROD migration
workflow must include PROD-only V126. V126 grants runtime only reviewed bounded
views and four run/recommendation procedures. It grants reviewer only reviewed
pending/evidence/history views and the two human review/handoff procedures.
It grants no base-table DML to either role. The six procedure ownerships go to
`WRITE_OWNER` with existing USAGE retained. V126 is checksum-locked and
forward-only; never run its SQL outside the protected migration ledger.
V114–V117, V119–V122, and V125 remain DEV-only; V118 remains unused.

## V126 partial-PROD recovery (Data #510)

Protected run `36516853207` ledgered V106–V113 and V123/V124, then failed in
V126 at query `01c76304-020b-bdce-0064-2d0701049282`. Query history proves
that `OH_LYME_PROD_MIGRATION_DEPLOY_SVC`, using
`OH_LYME_PROD_MIGRATION_DEPLOYER`, could not grant `SELECT` on
`GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS` to `WRITE_OWNER`. PROD's
`CATALOG_DISCOVERY_OBSERVATIONS` and `CATALOG_RESOURCES` are owned by
`ACCOUNTADMIN`; in DEV they are owned by the DEV migration deployer. The first
eleven V126 grants succeeded. V126 has no ledger receipt; later grants and all
six procedure ownership transfers were not reached. No objects are created or
replaced by V126. Repeating its earlier object grants is safe, while the
ownership transfers have not yet occurred. Preserve all partial grants and
ledger receipts. If a future run fails after any ownership transfer, stop and
reinspect the six procedure owners before another retry; replaying an ownership
transfer from a role that no longer owns the procedure is not assumed safe.

The two account-owned catalog grants now belong to the reviewed administrative
bootstrap, not the protected migration role. Before any protected retry, the
account owner must approve and execute **only** these missing statements with
the verified `BVB26657_PAT` `ACCOUNTADMIN` identity:

```sql
GRANT SELECT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS
  TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER;
GRANT SELECT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.CATALOG_RESOURCES
  TO ROLE OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER;
```

Current state has neither grant. Required state adds only table-level `SELECT`
to the non-login procedure owner; runtime/reviewer and the migration deployer
gain no new catalog DML or grant option. Inspect `SHOW GRANTS ON TABLE` and
`SHOW GRANTS TO ROLE` immediately afterward. If recovery is required before
V126 runs, the account owner can revoke these exact two grants from
`WRITE_OWNER`; after V126, revoke only through a reviewed procedure-dependency
and service-impact assessment.

This PR changes the **unledgered** V126 source and therefore its checksum.
Peer review of the exact new checksum is required; never edit V106–V113 or
V123/V124 receipts. The migration authority preflight now fails before any
migration DDL when pending V126 lacks either catalog grant. Re-fetch current
main and repeat exact-main Quality, DEV digest, PROD ledger, migration plan,
checksum, bootstrap and grant checks before dispatching one protected retry.
Do not launch DATA #495 operations as part of this recovery.

Before V126, verify exact role grants, the deployer hierarchy, and the PROD
ledger. After V126, verify effective privileges and both allow and deny cases
with separately authenticated PROD identities. Runtime must fail human review,
source approval, acquisition, ingestion, publication, migration, and direct
GOVERNANCE writes. Reviewer must fail runtime recommendation writes, broad
table DML, source approval, ingestion, publication, and migration. PROD
bootstrap and grants require their own live proof; DEV proof is not evidence
of PROD provisioning.

Assigning a human reviewer is a separate account owner or delegated security
administrator decision. Record the named individual's approval, confirm the
Snowflake user is individually authenticated and `USER_PERSON`, grant only the
PROD reviewer role to that user, and add an active exact-user row to the PROD
`DATASET_DISCOVERY.REVIEWER_ALLOWLIST` through a separately reviewed control.
Verify the role grant, allowlist, authenticated principal attribution, and
service/shared-principal rejection before review use. Do not assign reviewer
to arbitrary users or to the Dataset Discovery service. A PROD service user,
credential, or schedule likewise needs separate review.

### DATA #510 partial V126 recovery

Protected run 36516853207 applied V106–V113 and V123/V124, then failed before
ledgering V126. The unchanged V126 source checksum is
`97f2684ce6fff946d2c07c28cfae59d06482a985b8f38af827a151a09280da12`.
The [incident matrix](data-510-v126-grant-recovery.md) records the partial
grants and ownership. The first unauthorized grant targets the account-owned
`GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS`; `CATALOG_RESOURCES` has the same
gap. Query-history text was not visible to the narrow migration role, so the
failed statement is deterministically localized rather than confirmed by query
history.

The reviewed correction extends the account bootstrap with `SELECT WITH GRANT
OPTION` on only those two PROD catalog tables to the migration deployer. This
lets the unchanged V126 delegate only their `SELECT` privileges to
`WRITE_OWNER`. It gives no `MANAGE GRANTS`, database/schema ownership, or
account administration. Running these two new account-owner statements needs
**separate explicit owner approval**; merging code does not authorize them.
Record identity, script hash, query IDs, and post-grant role evidence.

The protected `migration-authority-preflight` checks both grant options when
V126 is pending and fails before migration execution when either is missing.
Before a reviewed retry, recheck the partial grants and procedure owners. The
ordinary grants already applied can be replayed; no V126 ownership transfers
are currently effective. If any transfer appears, stop and reassess replay
because `COPY CURRENT GRANTS` must not be assumed harmless after a transfer.

For recovery, disable the affected service credential or revoke exact
runtime/reviewer procedure USAGE and user-role assignments through a protected
security action. Preserve audit and handoff rows. Reconcile partial bootstrap
by inspecting grants before replaying exact idempotent statements. Correct
schema or object grants through a new forward-only migration, never by editing
V126 or its applied checksum.
