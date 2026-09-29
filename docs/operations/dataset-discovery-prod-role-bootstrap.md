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

For recovery, disable the affected service credential or revoke exact
runtime/reviewer procedure USAGE and user-role assignments through a protected
security action. Preserve audit and handoff rows. Reconcile partial bootstrap
by inspecting grants before replaying exact idempotent statements. Correct
schema or object grants through a new forward-only migration, never by editing
V126 or its applied checksum.
