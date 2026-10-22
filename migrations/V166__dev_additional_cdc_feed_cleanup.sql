-- DATA #132: extend the existing exact cleanup to two approved CDC metadata feeds.
-- Immutable capture+30-day leases, exact approvals, guard, audit and owner handoff remain.
-- Requires V143 already applied. Reserved by DATA #727. No DELETE is executed by this migration.
-- Separately approved SECURITYADMIN preparation must revoke executor USAGE,
-- transfer the existing procedure and expected-handoff view to the migration
-- deployer with REVOKE CURRENT GRANTS, and verify exact object identities.
-- Do not grant a normal migrator the purge-owner role or broader privileges.
-- CREATE OR REPLACE deliberately omits COPY GRANTS: execution stays closed
-- until a new separately approved V166 ownership/attestation handoff completes.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V AS
SELECT SHA256 AS MIGRATION_SHA256,
       '5f927aad5c15b3c5a4141b31bcbc84b7c41abb6f559598367ad55d05be459d4d' AS PROCEDURE_BODY_SHA256
FROM GOVERNANCE.SCHEMA_MIGRATIONS
WHERE VERSION='V166'
  AND FILENAME='V166__dev_additional_cdc_feed_cleanup.sql';

CREATE OR REPLACE PROCEDURE GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
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
    selected_source_id VARCHAR;
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
    FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS a
    JOIN GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V e
      ON e.MIGRATION_SHA256=a.MIGRATION_SHA256
     AND e.PROCEDURE_BODY_SHA256=a.PROCEDURE_BODY_SHA256
    WHERE a.OWNER_ROLE='OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER'
      AND LENGTH(a.HANDOFF_REF)>0 AND LENGTH(a.ATTESTED_BY)>0;
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
    SELECT COUNT(*),MAX(a.PLAN_CANONICAL_JSON),
           MAX(PARSE_JSON(a.PLAN_CANONICAL_JSON):source_ids[0]::VARCHAR)
      INTO :approval_count,:approved_plan,:selected_source_id
    FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS a
    WHERE a.PLAN_SHA256=:P_PLAN_SHA256
      AND SHA2(a.PLAN_CANONICAL_JSON,256)=a.PLAN_SHA256
      AND LENGTH(a.APPROVED_BY)>0 AND LENGTH(a.APPROVAL_REF)>0
      AND PARSE_JSON(a.PLAN_CANONICAL_JSON):environment::VARCHAR='DEV'
      AND ARRAY_SIZE(PARSE_JSON(a.PLAN_CANONICAL_JSON):source_ids)=1
      AND PARSE_JSON(a.PLAN_CANONICAL_JSON):source_ids[0]::VARCHAR
          IN ('cdc-eid-expedited','cdc-mmwr','cdc-newsroom')
      AND CURRENT_DATABASE()='ONE_HEALTH_LYME_GAP_ATLAS_DEV';
    IF (approval_count <> 1) THEN RAISE denied; END IF;
    -- RawCopy's canonical field order is fixed. The run token and lease hash
    -- are ASCII-safe, so this is the exact Python identity hash for this copy.
    IF (SHA2('{"environment":"DEV","kind":"checkpoint_payload",'
        || '"lease_sha256":"' || P_LEASE_SHA256 || '",'
        || '"locator":"' || checkpoint_uri || '",'
        || '"source_id":"' || selected_source_id || '"}',256)<>P_COPY_SHA256) THEN
        RAISE denied;
    END IF;


    -- One preselected bound plan; no correlated outer table alias in FLATTEN.
    SELECT COUNT(*) INTO :copy_count
    FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(:approved_plan):copies)) c
    WHERE c.value:kind::VARCHAR='checkpoint_payload'
      AND c.value:environment::VARCHAR='DEV'
      AND c.value:source_id::VARCHAR=:selected_source_id
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
      AND l.DOCUMENT:source_id::VARCHAR=:selected_source_id
      AND l.DOCUMENT:policy_version::VARCHAR='intelligence-raw-30d-v1'
      AND TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)
        = DATEADD(day,30,TO_TIMESTAMP_TZ(l.DOCUMENT:captured_at::VARCHAR))
      AND TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)<=DATEADD(hour,48,CURRENT_TIMESTAMP());
    IF (lease_count <> 1) THEN RAISE denied; END IF;

    SELECT COUNT(*) INTO :active_claims
    FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS c
    LEFT JOIN GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS l
      ON l.DOCUMENT_TYPE='lease'
      AND l.DOCUMENT_KEY=c.DOCUMENT:lease_sha256::VARCHAR
    WHERE c.DOCUMENT_TYPE='copy' AND c.DOCUMENT:locator::VARCHAR=:checkpoint_uri
      AND (l.DOCUMENT_KEY IS NULL
        OR COALESCE(c.DOCUMENT:source_id::VARCHAR,'')<>:selected_source_id
        OR COALESCE(c.DOCUMENT:environment::VARCHAR,'')<>'DEV'
        OR COALESCE(l.DOCUMENT:source_id::VARCHAR,'')<>:selected_source_id
        OR TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR) IS NULL
        OR TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:captured_at::VARCHAR) IS NULL
        OR TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)
          <>DATEADD(day,30,TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:captured_at::VARCHAR))
        OR COALESCE(l.DOCUMENT:policy_version::VARCHAR,'')<>'intelligence-raw-30d-v1'
        OR TRY_TO_TIMESTAMP_TZ(l.DOCUMENT:expires_at::VARCHAR)>DATEADD(hour,48,CURRENT_TIMESTAMP()));
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

GRANT SELECT ON VIEW GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V
    TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
-- Deliberately no executor procedure USAGE or ownership handoff.
