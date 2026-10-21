# DATA #680 operational readiness: non-mutating audit, 2026-10-20

No grants, credentials, migration, workflow dispatch, synthetic pair, acquisition, registration, deletion or API activation was performed. Inspection used the isolated `data680-proactive-cleanup-20261020` checkout. No secret values were read or printed.

## Current evidence and limits

* Installed Snowflake CLI named PAT `ATLAS_PROD_RUNTIME_AUDIT` authenticated as `MATTHEWCARAWAY` / `OH_LYME_PROD_RUNTIME` / `ONE_HEALTH_LYME_GAP_ATLAS_PROD` / `OH_LYME_PROD_INGEST_XS_WH` before inspection. This is a human audit identity, not executor proof.
* Runtime-visible SHOW USERS for the cleanup service, SHOW ROLES for the cleanup/purge-owner pattern, and SHOW PROCEDURES for the purge procedure returned empty visible results. They do **not** prove absence. SHOW GRANTS TO the cleanup user failed because this role lacks MANAGE GRANTS. No elevated connection was used.
* Initial runtime-role SELECT on `GOVERNANCE.SCHEMA_MIGRATIONS` was denied. The subsequently authorized named migration-role readback below resolves ledger visibility; protected service credentials and cleanup grants still need intended-actor proof.
* `GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS` currently has zero rows. The shared checkpoint is a permanent TABLE, owner `OH_LYME_PROD_MIGRATION_DEPLOYER`, retention_time=1, SHOW TABLES rows=4. Those four rows are not identified as EID and are outside deletion authorization. This is active storage/platform metadata, not proof of recovery-byte erasure.
* GitHub production environment exists, requires reviewer CarawayLabs, protected branches only, prevent_self_review=false. Agents must still never approve deployments. Production secret **names** include existing `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_PRIVATE_KEY_B64`, `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`, runtime key/user/role slots, shared SPACES_* and DIGITALOCEAN_ACCESS_TOKEN. No dedicated INTELLIGENCE_CLEANUP_* slots were present. Repository secret names contain only DIGITALOCEAN_MONITOR_READ_TOKEN. Slot presence does not attest secret values, identities or validity.
* No SNOWFLAKE_*, SPACES_*, DIGITALOCEAN_* or INTELLIGENCE_CLEANUP_* values are present in this process environment. No shared key was substituted.
* `doctl spaces keys list --format Name,Grants` returned metadata only from the current authenticated account: `oh-lyme-prod-github-ingestion-20260917` and `key-1787537551259` each have readwrite on PROD bucket; `oh-lyme-dev-ingestion-github-20260915-final` has readwrite on DEV; `allbuckets-1787199566016` has fullaccess. No key is identified by name as cleanup. The unnamed-purpose PROD key could have a separate owner: obtain ownership attestation instead of assuming absence or reusing it.
* No dedicated Spaces key is available for S3 metadata requests. Bucket versioning, historical versions, policy compatibility and lifecycle were not read back. The DigitalOcean control-plane key inventory does not prove these properties. Do not supply fullaccess/shared ingestion credentials to bypass this gap.

## Owner instructions: exact location and minimum privileges

1. **Snowflake security owner, separately approved operation:** in Snowsight SQL worksheet under the security-governed administrator, independently review `docs/contracts/intelligence/v2/prod-raw-cleanup-security-bootstrap-review.sql`. Create/verify `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP_SVC` as the dedicated service user and grant only `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP`. Configure its keypair public key on that service user; keep its private key/passphrase only in the approved operator secret store. Do not mint a personal-account PAT or grant the purge-owner role to any person/service. The bootstrap comment is corrected to keypair in this PR; the actual `plan`/`approve`/`execute` runner uses the existing keypair connection/settings path. PAT is used only for the named human audit dry-run.
2. **Minimum executor authority:** USAGE on PROD database, GOVERNANCE schema and `OH_LYME_PROD_INGEST_XS_WH`; SELECT on retention documents, approvals and handoff attestations; INSERT on redacted retention audit; SELECT/UPDATE on the single write guard; exact four-argument purge-procedure USAGE only after reviewed handoff. No direct checkpoint DELETE, CREATE, OWNERSHIP, MANAGE GRANTS, source registration or API grant. V150 supplies its table privileges; bootstrap supplies container access. Do not improvise grant-all/future-table grants.
3. **Unassigned purge owner:** `OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER` must have only USAGE on PROD database/GOVERNANCE, SELECT/DELETE on checkpoint table, the exact V150 dependency reads and guard SELECT/UPDATE, plus ownership of the exact purge procedure after handoff. `SHOW GRANTS OF ROLE` must prove it is unassigned. The owner-rights procedure is the sole physical checkpoint-delete seam.
4. **Migration authority readback:** owner of existing protected deployment credential must attest it resolves to `OH_LYME_PROD_MIGRATION_DEPLOY_SVC` / `OH_LYME_PROD_MIGRATION_DEPLOYER`, exact PROD DB/warehouse, then read exact V146/V150 ledger/checksums and procedure owner/body/creation timestamp. Do not grant ledger access to the cleanup user just to resolve this audit gap. Execution is separately approved through repository Actions `promote-prod.yml`, environment `production`; do not invoke migrations from a local admin connection. Preserve protected pending-set checks, immutable DEV image digest and native owner deployment approval. V146 and V150 are separate protected batches; any new correction migration must follow its own reviewed pending-set contract.
5. **Handoff:** after separately approved migration, security owner follows `prod-raw-cleanup-owner-handoff-review.sql`: zero outbound grants first, exact definition/dependencies verified by migration owner, transfer only procedure OWNERSHIP with REVOKE CURRENT GRANTS, verify purge-owner remains unassigned, grant executor USAGE last, write one immutable reviewed attestation. Fill approved reference/hash placeholders; never execute the unfilled template.
6. **DigitalOcean:** Control Panel > Spaces Object Storage > Access Keys > Create Access Key. Independently approve a separate named cleanup key, Limited Access, **only** bucket `one-health-lyme-gap-atlas-data-prod`, provider permission `Read/Write/Delete` (API `readwrite`). This is the narrowest provider preset supporting DELETE; do not choose All/Buckets-and-Objects. Code enforces the narrower EID key prefix because limited keys are bucket-scoped. Bucket settings must remain private, versioning disabled, no historical versions/delete markers at exact targets, and no incompatible bucket policy. If provider-enforced prefix restriction is mandatory, obtain a storage decision instead of silently widening credentials. Owner uses their authorized bucket-admin read access for versioning readback if limited key cannot read it; never grant bucket administration to executor.
7. **Where credentials go:** current cleanup command is an owner-controlled operator command, not a wired GitHub cleanup workflow. In its private execution context set `TOPX_ENV=prod`, `ENABLE_PRODUCTION_EXECUTION=true`, exact DB/user/role/warehouse, `SNOWFLAKE_PRIVATE_KEY_B64` (or private key path) and passphrase using the dedicated cleanup identity. Set exact `SPACES_BUCKET=one-health-lyme-gap-atlas-data-prod`, `SPACES_PREFIX=prod`, `SPACES_REGION=sfo3`, `SPACES_ENDPOINT=https://sfo3.digitaloceanspaces.com`. The read-only `dry-run` requires `INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID` / `INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY`; existing `execute` consumes SPACES_ACCESS_KEY_ID / SPACES_SECRET_ACCESS_KEY, mapped only from the dedicated cleanup key in that isolated process. Approval runs use the separate migration service, never executor credentials.
8. **GitHub settings:** existing promotion secrets are at https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/settings/environments > production > Environment secrets. Verify existing migration and runtime slots under their actual service owners; do not overwrite shared SNOWFLAKE_* or SPACES_* slots with cleanup values. If an approved protected cleanup job is later wired, add distinct cleanup Snowflake/keypair and INTELLIGENCE_CLEANUP_SPACES_* secrets in its approved environment and map them explicitly. Merely adding unused secrets does not provide an execution gate or prove readiness. No cleanup workflow exists in the inspected head; the only existing scheduled workflow is the CDC monitor.

## Remaining acceptance sequence (every write gate separate)

Correction PR exact-head review/CI and owner merge approval -> protected immutable promotion/migration approval -> dedicated security identity and Spaces credential provisioning approval -> exact owner/grant/body/attestation/config readback -> separately approved creation of the fixed synthetic two-copy pair -> SELECT/list/HEAD dry-run and private exact plan -> independent exact-plan approval -> separately authorized physical deletion with before/after active-store proof and normalized/provenance invariants -> verified daily proactive cadence/failure response -> separate EID source registration -> separate single bounded acquisition -> real V2 row evidence -> separate API #172 activation and service-identity canary -> Web genuine-article verification.

The retention decision now permits normal Snowflake Time Travel and Fail-safe. It does not authorize synthetic creation, deletion, migration execution, provisioning or acquisition. Do not require a fresh policy decision; require technical deadline enforcement and the distinct operation approvals.

Provider references checked: https://docs.digitalocean.com/products/spaces/how-to/manage-access/ ; https://docs.digitalocean.com/products/spaces/details/limits/ ; https://docs.digitalocean.com/reference/api/spaces/ .

## Proactive correction handoff supplement

V162 is proposed, not applied. Use the new
`prod-proactive-cleanup-owner-preparation-review.sql` only if existing V150
objects have already been handed off, then the protected exact V162-only or
ordered [V150,V162] batch after V146 verification. Final handoff uses
`prod-proactive-cleanup-owner-handoff-review.sql`, not the historical V150
template. Preserve old attestations; create one new exact migration/body/time
attestation. No security preparation, migration or handoff was executed.

Daily execution context, <=24-hour cadence, <=12-hour plan approval/execution,
immediate failure escalation with <=6-hour retry, and independently monitored
missed runs must be demonstrated before acquisition. See
[the proactive runbook](../operations/intelligence-proactive-cleanup-prod.md).
No new cleanup GitHub environment or workflow has been created.

## Supplemental authorized migration-role readback

# DATA #680 migration-authority read-only supplement

The task explicitly scopes non-mutating migration-authority inspection. Accordingly the named PAT `ATLAS_PROD_MIGRATOR` was used solely for identity, bounded ledger SELECT and SHOW metadata. No migration/security/provisioning statement was executed.

Identity: default connection authenticates `MATTHEWCARAWAY` / `OH_LYME_PROD_MIGRATION_DEPLOYER`, database null, warehouse COMPUTE_WH. The follow-up read explicitly selected `ONE_HEALTH_LYME_GAP_ATLAS_PROD` and `OH_LYME_PROD_INGEST_XS_WH`, revalidated all four identity fields, then inspected the ledger. This proves the human restricted PAT can read with the migration role; it does **not** validate the separately stored GitHub migration-service private key or service identity.

V146 is recorded with exact filename `V146__prod_intelligence_retention_and_v2_view.sql` and SHA256 `85a2fd022e4024bfb0217bad6cec78bdfcd1da255a662ebd5c48c7a073eb22dc`. V150 and V162 are not recorded. A full bounded ledger SELECT returned 111 rows (LIMIT 1000, below bound), compared locally with current checkout `migration_plan(PROD)` and source checksums.

Exactly two eligible pending migrations in this audited checkout:

* V150 `V150__prod_intelligence_raw_cleanup_authority.sql`, SHA256 `883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb`.
* V162 `V162__prod_intelligence_proactive_cleanup.sql`, SHA256 `451eda0f76fe21fda15058b59d1868804f7c32a49f87b21d77dd5f3b45c4b557` (working correction at audit time; recheck against final reviewed head before any deployment).

No unexpected source-checksum mismatch after accepting source line-ending equivalence and the existing explicit legacy hash allowlist. V022 has its known legacy hash. Ledger duplicates exist at V020, V028 and V071, two rows each. Do not repair or rewrite them; preserve existing migration-runner reconciliation rules. No ledger versions fall outside eligible PROD source plan. This is a metadata comparison, not a migration-runner execution or claim that every protected release preflight passes.

SHOW GRANTS TO migration role confirms database/schema/container/migration object access and ownership including checkpoint table, migration ledger and V2 presentation view, plus warehouse USAGE. The broad existing grants were not altered. Visible SHOW cleanup service/user roles/purge procedure remained empty even under this role, so dedicated actor and unassigned purge owner still require security-owner readback; absence is not established by restricted visibility.

This supplements the earlier runtime-denied ledger audit: the V146 status and pending set are now confirmed rather than unknown. Dedicated GitHub service-credential validity, cleanup security grants/handoff and Spaces versioning remain unresolved.
