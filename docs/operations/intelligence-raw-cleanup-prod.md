# PROD intelligence raw cleanup: CDC EID only

Status: implemented in source; not provisioned, deployed, handed off, scheduled,
or executed in PROD. DATA #680 is not complete until the separate live gates in
this runbook pass. This is the physical-retention gate for the single approved
CDC EID Expedited source. It does not approve a source, acquire content, or
activate API #172.

## Exact deletion boundary

The cleanup runner accepts only `environment=PROD` and source
`cdc-eid-expedited`. Its configured physical stores are:

- Snowflake `ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.INGESTION_RUN_PAYLOADS`,
  through `GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT`.
- DigitalOcean Spaces bucket `one-health-lyme-gap-atlas-data-prod`, region
  `sfo3`, endpoint `https://sfo3.digitaloceanspaces.com`, prefix `prod`, and
  the exact claimed key under `prod/prod/cdc-eid-expedited/<run>/<sha256>.bin`.
- Managed conditional-cache/process buffers for this same source and exact
  expired claims. No local file, arbitrary bucket, other feed, or other
  Snowflake table is accepted.

Only immutable captures whose recorded expiry is at least 30 days after their
original successful capture and is now expired are eligible. A live claim on a
shared object excludes it. Normalized item/revision/capture records, source
registry and versions, source attribution, retention documents, and audit
receipts are outside the deletion scope. Read paths reject expired raw bytes at
the 30-day boundary even if physical cleanup is awaiting the operator cadence.

## Required identities and privileges

Provision these only after independent security review. No secret value belongs
in Git, issue comments, workflow output, or this runbook.

| Identity | Intended access |
| --- | --- |
| `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP_SVC` / `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP` | Dedicated fixed-scope cleanup connection; exact PROD database/schema/warehouse usage; select claims/approvals/attestation; insert redacted audit receipts; update the existing serialization guard; procedure `USAGE`; no direct `DELETE`. |
| `OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER` | Unassigned owner role; exact `SELECT, DELETE` on `INGESTION_RUN_PAYLOADS`, and only the procedure's required claim/approval/attestation/guard reads and guard update. Never grant it to a user, ingestion runtime, API, migration service, or cleanup executor. |
| `OH_LYME_PROD_MIGRATION_DEPLOY_SVC` / `OH_LYME_PROD_MIGRATION_DEPLOYER` | Existing protected migration identity; inserts one exact canonical plan approval after the external review reference is approved. It does not execute deletion. |
| `SECURITYADMIN` | Existing role used only for the separately reviewed role grants, procedure ownership transfer, and one immutable handoff attestation. |
| DigitalOcean Spaces key | Separate PROD key limited to the PROD bucket with delete permission; code rejects every key outside the exact `prod/prod/cdc-eid-expedited/...` claimed key. Do not reuse ingestion or DEV credentials. |

The production credentials are not provided by this change. Snowflake key-pair
connection values and the PROD Spaces delete key must be provisioned in the
approved execution environment by their owners. The cleanup service must
validate `CURRENT_USER`, `CURRENT_ROLE`, `CURRENT_DATABASE`, and
`CURRENT_WAREHOUSE` before inventory or deletion.

## Protected rollout

1. Merge DATA PR #667 and use the existing protected production promotion to
   apply V146. Confirm V146 is recorded at the pinned checksum and the intended
   PROD V2 reader can read the exact `PRESENTATION.INTELLIGENCE_FEED_V2`
   contract. V150 must not be applied in the same batch as V146.
2. An authorized security owner reviews and applies
   [`prod-raw-cleanup-security-bootstrap-review.sql`](../contracts/intelligence/v2/prod-raw-cleanup-security-bootstrap-review.sql)
   outside the migration identity. Provision the dedicated service user and
   bucket key separately. Read back all grants and confirm the purge-owner role
   is unassigned and the cleanup executor has no direct `DELETE`.
3. Promote V150 through `.github/workflows/promote-prod.yml` with the existing
   protected `production` environment approval and these exact inputs:

   ```text
   expected_pending_json=[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql","sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"}]
   protected_intelligence_prerequisite=true
   ```

   The workflow and migration runner reject a mixed or changed pending set.
   V150 creates approval/attestation records and a four-argument owner-rights
   procedure; it grants no procedure `USAGE`, transfers no ownership, and
   performs no deletion.
4. Read back the exact V150 ledger checksum and SQL procedure body as the
   migration owner. Apply the reviewed
   [`prod-raw-cleanup-owner-handoff-review.sql`](../contracts/intelligence/v2/prod-raw-cleanup-owner-handoff-review.sql)
   with an authorized `SECURITYADMIN`: verify zero outbound grants, transfer
   ownership with `REVOKE CURRENT GRANTS`, verify the exact owner and dependency
   grants, grant executor `USAGE` last, then insert exactly one handoff
   attestation bound to the migration hash, body hash and current procedure
   creation time. Do not execute the template until its placeholders and
   independent review reference are approved.
5. Verify the cleanup identity's read-only handoff and grant checks. Run the
   offline synthetic proof described below before creating any real-source
   approval. Use an isolated restricted workspace for plan files; they contain
   private locators. The runner logs only plan hashes and outcome counts.
6. An independently approved reviewer approves the exact plan hash and
   inventory. Only a separate explicit production deletion authorization may
   invoke `execute --confirm` with that same hash. Replanning invalidates the
   approval. Retry of the same plan is safe and records already-absent objects
   without widening the target set.

No schedule is added by this PR. Before the first EID acquisition, the owner
must record the approved operating cadence and prove that each expired plan is
reviewed and executed promptly enough to meet the physical 30-day policy. If
that cadence is not staffed or cannot meet the boundary, EID acquisition stays
closed.

## Synthetic proof and current limit

The offline proof uses exactly one synthetic object key:

```text
s3://one-health-lyme-gap-atlas-data-prod/prod/prod/cdc-eid-expedited/synthetic-proof-680/35347e7199b7892e7a0202ed72eafc0147f5a28d1042f27a59d595c9d45fa6b2.bin
```

The focused test checks `HEAD`, one `DELETE`, retry as already absent, and
rejection of DEV and other-source targets. The focused suite parses a one-copy
synthetic PROD checkpoint plan, validates the V150 30-day predicate, and
asserts the SQL deletes only the raw checkpoint table. These are
fixture/provider-double checks, not live PROD deletion evidence. No synthetic PROD object or
lease has been created, and no PROD delete has run. A live one-target proof
still requires explicit authorization to create the synthetic target and then
delete it, plus before/after Snowflake and Spaces readback under the intended
identities. Verify normalized item/revision/capture/provenance counts are
unchanged in that separately authorized proof.
