# Dataset Discovery DEV role bootstrap and grant gate

ADR 0041 approved the three-role architecture for DEV. The protected schema
migration identity cannot create account roles or grant `READ SESSION`, so the
account-level bootstrap in
[`scripts/bootstrap_dataset_discovery_roles_dev.sql`](../../scripts/bootstrap_dataset_discovery_roles_dev.sql)
is a separately reviewed administrative action. It is not a replacement for
the checksum-locked migration ledger. V106–V113 remain protected migrations;
DEV-only V114 grants precise object access and transfers procedure ownership
only after those objects exist.

Before the bootstrap, verify #454's V103/V104 recovery, the live V105 ledger
receipt, the accepted ADR, and the exact administrative connection identity.
Use only the named `BVB26657_PAT` connection for this explicitly authorized
DEV account-level action. Its effective role must be `ACCOUNTADMIN`; never use
the account-admin PAT as an application runtime or reviewer credential. Do not
print PAT values or fall back to interactive authentication.

```powershell
snow sql -c BVB26657_PAT -q "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()" --format JSON
snow sql -c BVB26657_PAT -f scripts/bootstrap_dataset_discovery_roles_dev.sql
```

The file creates only three `OH_LYME_DEV_DATASET_DISCOVERY_*` roles, grants
`READ SESSION` only to the non-login write owner, and places that owner role
under `OH_LYME_DEV_MIGRATION_DEPLOYER` for Snowflake's ownership-transfer
rule. It assigns no reviewer or runtime user. Account-role bootstrap must be
audited separately from the migration ledger; record the reviewed file SHA,
query IDs, role grants and effective hierarchy without credentials.

Before V114 can run, confirm these exact grants with read-only `SHOW GRANTS TO
ROLE` and reject any unexpected inherited role or privilege. V114 grants no
base-table DML to runtime/reviewer. It grants the write owner only the listed
procedure dependencies and moves ownership of the six reviewed procedures.
Run V106–V114 only through the protected DEV workflow, then verify receipts
and effective grants. No PROD bootstrap or V114 grant is included here.

Individual reviewer-role assignment, allowlist population, and a scoped
runtime service credential are separate attributable onboarding actions.
They require live `USER_PERSON`/service denial tests before either identity
is used for the end-to-end DEV proof. Do not substitute `ACCOUNTADMIN` or the
ingestion runtime for either identity.
