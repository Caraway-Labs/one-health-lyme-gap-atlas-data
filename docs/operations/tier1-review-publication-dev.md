# DATA #617: pinned Tier 1 DEV publication

This is the Data-owned persistence leg of ML #32. V140 is DEV-only and accepts
only the post-merge ML PR #103 batch `tier1-review-priority-744b2933bae43718`.
It is not a model registry or a PROD publication path. The selected statistical
reference model is surveillance-review priority, not disease risk.

## Source and byte contract

The preserved operator files are in
`C:\Users\caraw\Documents\Codex\2026-10-05\ml-32-final-publication-artifacts`.
`HANDOFF_STATUS.md` records individual SHA-256 values. The offline publisher
verifies those file hashes, manifest/lineage, the exact sorted FIPS-set hash,
counts, and the canonical output digest before any Snowflake call. It never
regenerates an ML result.

The ML builder computes SHA-256 over UTF-8 bytes of
`json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False)`.
Rows are sorted by `county_fips`. V140 stages the exact per-row canonical Python
JSON strings, then hashes `[` + the strings joined by `,` in FIPS order + `]`.
It parses the rows separately for field validation and the view. Snowflake
`TO_JSON(VARIANT)` is never used for digest verification; it may change numeric
formatting or object-key order.

## Protected bootstrap gate

Account-level role creation and grants are **not** part of V140. A security
reviewer must approve the exact DEV-only
[`bootstrap_tier1_review_roles_dev.sql`](../../scripts/bootstrap_tier1_review_roles_dev.sql)
and its target identities. Before execution, record
`CURRENT_USER`, `CURRENT_ROLE`, `CURRENT_DATABASE`, and `CURRENT_WAREHOUSE`
under the specifically authorized administrative PAT connection. Inspect
existing roles and grants; if either role already exists with unexpected
privileges or hierarchy, stop. Do not use interactive authentication.

`OH_LYME_DEV_TIER1_PUBLICATION_OWNER` is a non-login owner role. Its grants are
DEV database/schema usage; `CREATE TABLE` and `CREATE PROCEDURE` on
`FEATURE_STORE`; `CREATE VIEW` on `PRESENTATION`; `SELECT` on exactly
`PRESENTATION.SEMANTIC_RELEASES` and `SEMANTIC_COUNTY_ATLAS`; `SELECT, INSERT`
on `GOVERNANCE.SCHEMA_MIGRATIONS`; and usage on the DEV ingest warehouse. The
protected migration service user receives the role so the reviewed runner can
execute V140 and record its checksum. This role is not assigned to ML runtime.

`OH_LYME_DEV_ML_PUBLISHER` receives only DEV database/`FEATURE_STORE` schema
and warehouse usage before V140. V140 then grants only `USAGE` on the three
Tier 1 procedures. It receives no direct table DML or SELECT. A distinct,
role-restricted service user/PAT requires separate security onboarding and
denial proof. No owner/admin PAT is a substitute for publisher authentication.
The existing `OH_LYME_DEV_READ` receives `SELECT` only on
`PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V` through V140. It receives no
FEATURE_STORE table privileges or publisher procedure usage.

## Migration and publication sequence

1. Review and merge the Data PR. Verify the exact merged commit on `origin/main`.
2. Complete and audit the protected role bootstrap. Confirm owner role reachability
   from the DEV migration service identity; inspect the publisher role for no DML.
3. Read the DEV migration ledger under `ATLAS_DEV_READ`; use the exact pending
   `version`, `filename`, and source SHA-256 array for the protected
   `deploy-dev.yml` workflow. V138 may precede V140 if still pending. Do not
   apply V140 manually or skip an earlier migration.
4. Verify the V140 ledger receipt and exact object ownership/grants.
   After that receipt, the separately authorized administrator retires the
   owner's migration-only privileges and service assignment while preserving
   ownership of the Tier 1 objects and the exact source-table reads:

   ```sql
   REVOKE CREATE TABLE, CREATE PROCEDURE ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.FEATURE_STORE
     FROM ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER;
   REVOKE CREATE VIEW ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.PRESENTATION
     FROM ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER;
   REVOKE SELECT, INSERT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.SCHEMA_MIGRATIONS
     FROM ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER;
   REVOKE USAGE ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE
     FROM ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER;
   REVOKE USAGE ON WAREHOUSE OH_LYME_DEV_INGEST_XS_WH
     FROM ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER;
   REVOKE ROLE OH_LYME_DEV_TIER1_PUBLICATION_OWNER
     FROM USER OH_LYME_DEV_MIGRATION_DEPLOY_SVC;
   ```

   Review `SHOW GRANTS TO ROLE` afterward. A later replacement migration would
   require a fresh, reviewed temporary grant window.
5. Run the publisher's offline check, then use the reviewed named publisher PAT
   connection for the live call:

   ```powershell
   uv run python scripts/publish_tier1_review_dev.py 'C:\Users\caraw\Documents\Codex\2026-10-05\ml-32-final-publication-artifacts'
   uv run python scripts/publish_tier1_review_dev.py 'C:\Users\caraw\Documents\Codex\2026-10-05\ml-32-final-publication-artifacts' --publish --connection <reviewed-dev-ml-publisher-connection>
   ```

The script checks effective user, role, database, and warehouse before the
first call. It calls `SP_BEGIN_TIER1_REVIEW_BATCH`, stages at most 200 canonical
rows per call, and calls `SP_FINALIZE_TIER1_REVIEW_BATCH`.

Each procedure updates the precreated singleton lock row inside a transaction.
Stage retry with identical bytes is idempotent; a changed row is rejected.
Finalization verifies the pinned governed release/bundle, exactly 3,144 unique
source counties, exact set equality in both directions with
`PRESENTATION.SEMANTIC_COUNTY_ATLAS` for that release, selected row lineage and
values, reason bounds, expected tier/sufficiency counts, and byte-stable digest.
It changes batch state and active pointer in one transaction. A failure rolls
back and keeps the prior active batch. A retry after committed approval returns
the existing approval.

## Live acceptance evidence

After deployment, record the effective identity and migration ledger. Under the
owner identity verify one approved manifest, the active pointer, 3,144 unique
view FIPS, HIGH 315 / MEDIUM 628 / LOW 2,201, SUFFICIENT 651 /
INSUFFICIENT 2,493, no NOT_ESTIMABLE, selected model only, and the output digest.
Under the intended API read identity, prove `SELECT` of representative view
rows with every required field; prove base FEATURE_STORE table SELECT and
publisher procedure calls are denied. Under the publisher role, prove direct
table DML is denied. Record query IDs and redacted results in DATA #617.

Before approval, exercise duplicate, missing, substituted valid-looking FIPS,
wrong release/bundle/model/feature/policy, malformed tier/reasons, incomplete
stage, changed-digest replay, concurrent finalization, and lost-acknowledgment
retry in an isolated test database or transactionally protected test batch.
After each rejected attempt verify the prior active view still reads. The
hard-pinned live V140 procedure accepts only the authoritative identity, so
adversarial tests must not try to mutate the approved DEV batch. Record the
test environment and distinguish that evidence from live DEV publication.

## PROD boundary

ML #32 and API #10 do not explicitly require a PROD batch before API
development; API #10's production delivery will require a separately reviewed
PROD-compatible release/batch and protected promotion. V140 is excluded from
the PROD migration plan. This DEV release ID and bundle must never be copied
into PROD or treated as a PROD approval.
