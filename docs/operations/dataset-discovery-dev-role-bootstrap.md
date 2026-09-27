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
rule. It also grants database reachability, Governance schema reachability,
one account-owned catalog-table read, and warehouse usage because the
protected migration role cannot grant privileges on those objects. It assigns
no reviewer or runtime user. Account-role bootstrap must be
audited separately from the migration ledger; record the reviewed file SHA,
query IDs, role grants and effective hierarchy without credentials.

Before V114 can run, confirm these exact grants with read-only `SHOW GRANTS TO
ROLE` and reject any unexpected inherited role or privilege. The bootstrap is
safe to replay after a partial protected run: repeated `CREATE ROLE IF NOT
EXISTS` and exact grants resolve to the same roles and privileges. V114 grants no
base-table DML to runtime/reviewer. It grants the write owner only the listed
procedure dependencies and moves ownership of the six reviewed procedures.
Run V106–V114 only through the protected DEV workflow, then verify receipts
and effective grants. No PROD bootstrap or V114 grant is included here.

Individual reviewer-role assignment, allowlist population, and a scoped
runtime service credential are separate attributable onboarding actions.
They require live `USER_PERSON`/service denial tests before either identity
is used for the end-to-end DEV proof. Do not substitute `ACCOUNTADMIN` or the
ingestion runtime for either identity.

The separately reviewed DEV service-user bootstrap is
[`scripts/bootstrap_dataset_discovery_runtime_user_dev.sql`](../../scripts/bootstrap_dataset_discovery_runtime_user_dev.sql).
It creates `OH_LYME_DEV_DATASET_DISCOVERY_SVC` with `TYPE = SERVICE_AGENT`, grants
only `OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME`, and assigns the dedicated
`ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY.DATASET_DISCOVERY_SERVICE_AGENT_AUTH`
authentication policy to that user alone. That policy allows only
`PROGRAMMATIC_ACCESS_TOKEN`, requires role restriction for service users, and
sets `NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED`. It does not alter the
account-wide policy. A future network policy attached to this user would still
be enforced. This is DEV manual/shadow scope; PROD hardening may later evaluate
workload identity federation or fixed-egress network policy.

Before execution, verify the
administrative connection identity and check whether that user already exists;
after execution, inspect the exact user-role grant, `SHOW AUTHENTICATION POLICIES
ON USER`, `SHOW AUTHENTICATION POLICIES ON ACCOUNT`, and `DESCRIBE AUTHENTICATION
POLICY` results. An existing policy is not replaced by `IF NOT EXISTS`; any
unexpected properties require a separate reviewed correction. Create a role-restricted PAT
as a distinct credential step, with the secret captured directly into an
approved local credential store and later a DigitalOcean managed secret. Do
not include a token value in SQL files, CLI arguments, logs, review artifacts,
or Git. A service-user login must resolve to the runtime role and must fail
human review and handoff procedure calls. Do not assign either the reviewer or
write-owner role to this user. This DEV bootstrap does not authorize PROD.
