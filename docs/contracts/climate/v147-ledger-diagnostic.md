# V147 DEV ledger diagnostic: execution not authorized

Run 38509005000 passed metadata checks 1–8 and stopped at check 9 with
`DUPLICATE_MIGRATION_VERSIONS`. The returned duplicate identities were not retained
in the sanitized receipt. No particular version, conflicting checksum, historical
reconciliation or parser defect is established by that receipt.

The preflight parses connector column names to lowercase and preserves every row.
It rejects duplicate version keys before checking canonical filenames/checksums or
computing pending migrations. The canonical migration runner instead materializes
`dict(cursor.fetchall())` for version/checksum state; that can collapse duplicates,
but is not a governed justification for accepting or choosing between them. The
legacy V028/V029/V033 reconciliation checks remain unchanged. V136/V148–V150 and
all immutable migration sources remain unchanged. No acceptance rule is relaxed.

The existing protected `deploy-dev.yml` supports `ledger_diagnostic_only=true`
only alongside `metadata_preflight_only=true`. All other modes must be false,
`expected_pending_json=[]`, diagnostic query input empty, exact green main SHA
in `reviewed_commit`, and current owner budget evidence supplied. The existing
protected identity, main/Quality guards and exclusive early exit are reused.

Exactly three existing checksum-pinned statements execute in this order:

1. Effective user/role/database/warehouse/region/account identity.
2. SHOW WAREHOUSES for OH_LYME_DEV_INGEST_XS_WH and existing cost-capability checks.
3. SELECT version, filename, sha256, applied_at from DEV GOVERNANCE.SCHEMA_MIGRATIONS,
   ORDER BY version LIMIT 151 (the original statement 9).

No arbitrary SQL, DDL, DML, migrations, observation reads, grants, ingestion,
publication or unrelated reads are admitted. The service remains
OH_LYME_DEV_MIGRATION_DEPLOY_SVC / OH_LYME_DEV_MIGRATION_DEPLOYER. Existing
180-second process deadline +15-second termination grace, 60-second statement,
10-second queue and 65-second network/socket limits remain; no application,
workflow or operator retry. Connection closes without transaction or retry.

The receipt preserves every bounded record's version, filename, checksum and
application timestamp, duplicate row counts, identical-source versus conflicting-
source classification and canonical/current/line-ending/authorized-legacy match.
Malformed fields stop with a controlled category and are not printed. Unexpected
versions are reported as such. At 151 rows the receipt explicitly marks incomplete
coverage and blocks; no partial result proves uniqueness. Identical-source entries
retain different timestamps and all occurrences. Diagnostic completion means
evidence captured, not ledger acceptance, pending-set acceptance or V147 readiness.

Proposed authorization: **one protected DEV session, three read-only statements,
independent $7 maximum, no retries**, at the resulting exact green merged-main SHA.
Use owner-verified TXB06009 hash, Standard/AWS/AWS_US_WEST_2 and the owner-supplied
$2/credit public planning rate. Retain the existing larger conservative reservation
of $2.90625 (315s compute envelope +20 resume allowances +$1 reserve); do not credit
unused prior authorization or infer actual billing. The price input is checked for
freshness and ceiling before login. No Snowflake execution is authorized by merge.

After evidence: assess each duplicate against canonical rules without deleting,
rewriting or silently deduplicating history. Conflicts need explicit reconciliation
and state evidence; matching entries need a reviewed equivalence rule if supported.
Then complete the remaining metadata acceptance checks under new authorization.
V147 application and January observation readback each remain separately gated.
