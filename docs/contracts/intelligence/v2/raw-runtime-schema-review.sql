-- UNAPPLIED REVIEW TEMPLATE, not a numbered migration or executable rollout.
-- Replaces the unused fielded-ledger proposal in raw-retention-ledger-review.sql.
-- Parent allocates migration and dedicated least-privilege purge owner, verifies
-- intended roles in DEV, and coordinates the shared deployment slot. No Alpha.
-- Runtime never receives DELETE on shared scientific checkpoint/provenance data.

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS (
    DOCUMENT_TYPE VARCHAR(32) NOT NULL,
    DOCUMENT_KEY VARCHAR(256) NOT NULL,
    DOCUMENT_SHA256 VARCHAR(64) NOT NULL,
    DOCUMENT VARIANT NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- lease/capture/validation/run/copy/write_complete/buffer_release only:
-- bounded structured metadata, never XML,
-- base64 or raw feed body. Standard-table uniqueness is enforced under V135's
-- existing write guard by the runtime, not assumed from unenforced constraints.

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT (
    RECEIPT_SHA256 VARCHAR(64) NOT NULL,
    DOCUMENT VARIANT NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Independent committed append-only audit transaction/table: pending intent
-- must survive outer claim-lock rollback or a crash after physical deletion.

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS (
    PLAN_SHA256 VARCHAR(64) NOT NULL,
    PLAN_CANONICAL_JSON VARCHAR NOT NULL,
    APPROVED_BY VARCHAR(128) NOT NULL,
    APPROVED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Only the trusted owner can INSERT an exact reviewed plan. Runtime has no
-- INSERT/UPDATE/DELETE on approvals and no right to self-approve a cleanup.

CREATE PROCEDURE GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
    P_PLAN_SHA256 VARCHAR, P_RUN_ID VARCHAR, P_LEASE_SHA256 VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    denied EXCEPTION (-20001, 'INTELLIGENCE_RAW_DELETE_SCOPE_INVALID');
    approval_count INTEGER;
    lease_count INTEGER;
    active_claims INTEGER;
    payload_count INTEGER;
    mismatches INTEGER;
    deleted_count INTEGER;
    checkpoint_uri VARCHAR;
BEGIN
    -- Caller retains this transaction/guard across the complete exact-plan
    -- cleanup. Direct unguarded/autocommit calls fail closed.
    IF (CURRENT_TRANSACTION() IS NULL) THEN
        RAISE denied;
    END IF;
    UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD
      SET write_sequence=write_sequence+1 WHERE guard_id=1;
    IF (SQLROWCOUNT <> 1) THEN RAISE denied; END IF;
    IF (NOT REGEXP_LIKE(P_RUN_ID, '^[A-Za-z0-9_.:-]{1,128}$')
        OR NOT REGEXP_LIKE(P_PLAN_SHA256, '^[a-f0-9]{64}$')
        OR NOT REGEXP_LIKE(P_LEASE_SHA256, '^[a-f0-9]{64}$')) THEN
        RAISE denied;
    END IF;
    checkpoint_uri := 'snowflake://' || CURRENT_DATABASE()
      || '/GOVERNANCE/INGESTION_RUN_PAYLOADS/' || P_RUN_ID;

    SELECT COUNT(*) INTO :approval_count
    FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS a
    WHERE a.PLAN_SHA256=:P_PLAN_SHA256
      AND SHA2(a.PLAN_CANONICAL_JSON,256)=a.PLAN_SHA256
      AND PARSE_JSON(a.PLAN_CANONICAL_JSON):environment::VARCHAR
        = IFF(CURRENT_DATABASE()='ONE_HEALTH_LYME_GAP_ATLAS_DEV','DEV','PROD')
      AND CURRENT_DATABASE() IN
        ('ONE_HEALTH_LYME_GAP_ATLAS_DEV','ONE_HEALTH_LYME_GAP_ATLAS_PROD')
      AND EXISTS (
        SELECT 1 FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(a.PLAN_CANONICAL_JSON):copies)) c
        WHERE c.value:kind::VARCHAR='checkpoint_payload'
          AND c.value:locator::VARCHAR=:checkpoint_uri
          AND c.value:lease_sha256::VARCHAR=:P_LEASE_SHA256
      );
    IF (approval_count <> 1) THEN RAISE denied; END IF;

    SELECT COUNT(DISTINCT l.DOCUMENT_KEY) INTO :lease_count
    FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS l
    JOIN GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS r
      ON r.DOCUMENT_TYPE='run' AND r.DOCUMENT:run_id::VARCHAR=:P_RUN_ID
      AND r.DOCUMENT:lease_sha256::VARCHAR=l.DOCUMENT_KEY
    WHERE l.DOCUMENT_TYPE='lease' AND l.DOCUMENT_KEY=:P_LEASE_SHA256
      AND l.DOCUMENT:policy_version::VARCHAR='intelligence-raw-30d-v1'
      AND TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)
        = DATEADD(day,30,TO_TIMESTAMP_TZ(l.DOCUMENT:captured_at::VARCHAR))
      AND TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)<=CURRENT_TIMESTAMP();
    IF (lease_count <> 1) THEN RAISE denied; END IF;

    SELECT COUNT(*) INTO :active_claims
    FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS c
    JOIN GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS l
      ON l.DOCUMENT_TYPE='lease'
      AND l.DOCUMENT_KEY=c.DOCUMENT:lease_sha256::VARCHAR
    WHERE c.DOCUMENT_TYPE='copy' AND c.DOCUMENT:locator::VARCHAR=:checkpoint_uri
      AND TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)>CURRENT_TIMESTAMP();
    IF (active_claims <> 0) THEN RAISE denied; END IF;

    SELECT COUNT(*), COUNT_IF(payload:raw_lease_sha256::VARCHAR IS NULL
       OR payload:raw_lease_sha256::VARCHAR<>:P_LEASE_SHA256)
      INTO :payload_count,:mismatches
    FROM GOVERNANCE.INGESTION_RUN_PAYLOADS WHERE ingestion_run_id=:P_RUN_ID;
    IF (payload_count>1 OR mismatches>0) THEN RAISE denied; END IF;
    IF (payload_count=0) THEN RETURN 'already_absent'; END IF;
    DELETE FROM GOVERNANCE.INGESTION_RUN_PAYLOADS
      WHERE ingestion_run_id=:P_RUN_ID
        AND payload:raw_lease_sha256::VARCHAR=:P_LEASE_SHA256;
    deleted_count := SQLROWCOUNT;
    IF (deleted_count<>1) THEN RAISE denied; END IF;
    RETURN 'deleted';
END;
$$;

-- Bootstrap/review requirements, not executed grants:
-- * Runtime: SELECT/INSERT on retention documents, INSERT on audit, existing
--   V135 SELECT/UPDATE write guard, and USAGE on the scoped purge procedure.
-- * Dedicated purge owner: direct SELECT on approvals/documents, SELECT/DELETE
--   on INGESTION_RUN_PAYLOADS and SELECT/UPDATE on V135 guard only; no scientific
--   object-store access, normalized/item/revision deletion or API approval rights.
-- * Trusted approval operator: INSERT on approvals; runtime cannot assume role.
-- * No table/view/security alteration is performed by the Python runtime.
-- * Validate this procedure in DEV before assigning migration/production slot.
-- Snowflake scripting references:
-- https://docs.snowflake.com/en/developer-guide/snowflake-scripting/dml-status
-- https://docs.snowflake.com/en/developer-guide/snowflake-scripting/exceptions
