-- DATA #132/#135: DEV-only exact-plan raw cleanup authority.
-- V142 owns the lease/audit tables. This migration does not approve or execute a plan.
-- It creates a separate append-only security attestation for the later handoff.
-- The executor can read claims and invoke one scoped owner-rights procedure,
-- but has no direct DELETE on checkpoints or normalized/provenance tables.
USE DATABASE {{ DATABASE }};

-- Both roles and their database/schema usage are provisioned by the separately
-- reviewed DEV security bootstrap before this protected migration is dispatched.

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS (
    PLAN_SHA256 VARCHAR(64) NOT NULL,
    PLAN_CANONICAL_JSON VARCHAR NOT NULL,
    APPROVED_BY VARCHAR(128) NOT NULL,
    APPROVAL_REF VARCHAR(256) NOT NULL,
    APPROVED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Post-handoff security evidence is append-only and separate from plan approval.
-- The cleanup executor can read it but cannot insert or rewrite it.
CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS (
    MIGRATION_SHA256 VARCHAR(64) NOT NULL,
    PROCEDURE_BODY_SHA256 VARCHAR(64) NOT NULL,
    PROCEDURE_CREATED_ON TIMESTAMP_LTZ NOT NULL,
    OWNER_ROLE VARCHAR(128) NOT NULL,
    HANDOFF_REF VARCHAR(256) NOT NULL,
    ATTESTED_BY VARCHAR(128) NOT NULL,
    ATTESTED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Only the protected migration/approval service may insert. The runtime and
-- cleanup executor receive no INSERT/UPDATE/DELETE on this table.

-- The older checkpoint table DELETE dependency is granted to the unassigned
-- owner role by the reviewed DEV security bootstrap, not this migrator.
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT SELECT, UPDATE ON TABLE GOVERNANCE.INTELLIGENCE_WRITE_GUARD
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
CREATE PROCEDURE GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
    P_PLAN_SHA256 VARCHAR, P_RUN_ID VARCHAR, P_LEASE_SHA256 VARCHAR,
    P_COPY_SHA256 VARCHAR
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    denied EXCEPTION (-20001, 'INTELLIGENCE_RAW_DELETE_SCOPE_INVALID');
    approval_count INTEGER;
    handoff_count INTEGER;
    approved_plan VARCHAR;
    copy_count INTEGER;
    pending_count INTEGER;
    lease_count INTEGER;
    active_claims INTEGER;
    payload_count INTEGER;
    mismatches INTEGER;
    deleted_count INTEGER;
    checkpoint_uri VARCHAR;
BEGIN
    -- Even an accidental early USAGE grant cannot activate a procedure still
    -- owned by the migration deployer. INVOKER_ROLE is the effective owner in
    -- an owner-rights procedure.
    IF (INVOKER_ROLE() <> 'OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER') THEN
        RAISE denied;
    END IF;
    SELECT COUNT(*) INTO :handoff_count
    FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
    WHERE OWNER_ROLE='OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER'
      AND LENGTH(HANDOFF_REF)>0 AND LENGTH(ATTESTED_BY)>0;
    IF (handoff_count <> 1) THEN RAISE denied; END IF;
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
        OR NOT REGEXP_LIKE(P_LEASE_SHA256, '^[a-f0-9]{64}$')
        OR NOT REGEXP_LIKE(P_COPY_SHA256, '^[a-f0-9]{64}$')) THEN
        RAISE denied;
    END IF;
    checkpoint_uri := 'snowflake://' || CURRENT_DATABASE()
      || '/GOVERNANCE/INGESTION_RUN_PAYLOADS/' || P_RUN_ID;
    -- RawCopy's canonical field order is fixed. The run token and lease hash
    -- are ASCII-safe, so this is the exact Python identity hash for this copy.
    IF (SHA2('{"environment":"DEV","kind":"checkpoint_payload",'
        || '"lease_sha256":"' || P_LEASE_SHA256 || '",'
        || '"locator":"' || checkpoint_uri || '",'
        || '"source_id":"cdc-eid-expedited"}',256)<>P_COPY_SHA256) THEN
        RAISE denied;
    END IF;

    SELECT COUNT(*),MAX(a.PLAN_CANONICAL_JSON) INTO :approval_count,:approved_plan
    FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS a
    WHERE a.PLAN_SHA256=:P_PLAN_SHA256
      AND SHA2(a.PLAN_CANONICAL_JSON,256)=a.PLAN_SHA256
      AND LENGTH(a.APPROVED_BY)>0 AND LENGTH(a.APPROVAL_REF)>0
      AND PARSE_JSON(a.PLAN_CANONICAL_JSON):environment::VARCHAR='DEV'
      AND TO_JSON(PARSE_JSON(a.PLAN_CANONICAL_JSON):source_ids)='["cdc-eid-expedited"]'
      AND CURRENT_DATABASE()='ONE_HEALTH_LYME_GAP_ATLAS_DEV';
    IF (approval_count <> 1) THEN RAISE denied; END IF;
    -- One preselected bound plan; no correlated outer table alias in FLATTEN.
    SELECT COUNT(*) INTO :copy_count
    FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(:approved_plan):copies)) c
    WHERE c.value:kind::VARCHAR='checkpoint_payload'
      AND c.value:environment::VARCHAR='DEV'
      AND c.value:source_id::VARCHAR='cdc-eid-expedited'
      AND c.value:locator::VARCHAR=:checkpoint_uri
      AND c.value:lease_sha256::VARCHAR=:P_LEASE_SHA256;
    IF (copy_count <> 1) THEN RAISE denied; END IF;
    -- The separate append-only execution audit must contain a committed intent
    -- before this owner-rights routine can mutate the checkpoint table.
    SELECT COUNT(*) INTO :pending_count
    FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT a
    WHERE a.DOCUMENT:plan_sha256::VARCHAR=:P_PLAN_SHA256
      AND a.DOCUMENT:copy_sha256::VARCHAR=:P_COPY_SHA256
      AND a.DOCUMENT:outcome::VARCHAR='pending';
    IF (pending_count = 0) THEN RAISE denied; END IF;

    SELECT COUNT(DISTINCT l.DOCUMENT_KEY) INTO :lease_count
    FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS l
    JOIN GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS r
      ON r.DOCUMENT_TYPE='run' AND r.DOCUMENT:run_id::VARCHAR=:P_RUN_ID
      AND r.DOCUMENT:lease_sha256::VARCHAR=l.DOCUMENT_KEY
    WHERE l.DOCUMENT_TYPE='lease' AND l.DOCUMENT_KEY=:P_LEASE_SHA256
      AND l.DOCUMENT:source_id::VARCHAR='cdc-eid-expedited'
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

GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
    TO ROLE SECURITYADMIN;
GRANT INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT SELECT, UPDATE ON TABLE GOVERNANCE.INTELLIGENCE_WRITE_GUARD
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
-- Deliberately no procedure USAGE or OWNERSHIP handoff here. The separately
-- reviewed SECURITYADMIN phase transfers ownership, verifies the definition
-- and dependency grants, then grants exact executor USAGE last.
