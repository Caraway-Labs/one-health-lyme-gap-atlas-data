-- DATA #617. Pinned DEV-only ML #32 output. Account role bootstrap is separate.
-- Execute as OH_LYME_DEV_TIER1_PUBLICATION_OWNER through the reviewed migration runner.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS FEATURE_STORE.TIER1_REVIEW_BATCHES (
  batch_id VARCHAR NOT NULL,
  output_sha256 VARCHAR(64) NOT NULL,
  source_commit VARCHAR(40) NOT NULL,
  generated_at_utc VARCHAR NOT NULL,
  release_id VARCHAR NOT NULL,
  bundle_sha256 VARCHAR(64) NOT NULL,
  model_version VARCHAR NOT NULL,
  feature_set_version VARCHAR NOT NULL,
  evaluation_version VARCHAR NOT NULL,
  tier_policy_version VARCHAR NOT NULL,
  expected_rows NUMBER NOT NULL,
  state VARCHAR NOT NULL,
  created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  approved_at TIMESTAMP_LTZ
);

-- row_json is the exact UTF-8-compatible canonical Python JSON row string.
-- SHA2 is computed over '[' + rows ordered by FIPS and joined with ',' + ']'.
-- Parsing to VARIANT is for validation and the read view only, never for hashing.
CREATE TABLE IF NOT EXISTS FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS (
  batch_id VARCHAR NOT NULL,
  county_fips VARCHAR(5) NOT NULL,
  row_json VARCHAR NOT NULL,
  staged_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH (
  pointer_key VARCHAR NOT NULL,
  batch_id VARCHAR,
  activated_at TIMESTAMP_LTZ
);
INSERT INTO FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH(pointer_key, batch_id)
SELECT 'TIER1_COUNTY_REVIEW', NULL
WHERE NOT EXISTS (
  SELECT 1 FROM FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH
  WHERE pointer_key = 'TIER1_COUNTY_REVIEW'
);

-- The precreated row is updated inside each publisher transaction. Snowflake
-- enforces a write conflict/lock on this row; informational keys are not used.
CREATE TABLE IF NOT EXISTS FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK (
  lock_name VARCHAR NOT NULL,
  revision NUMBER NOT NULL
);
INSERT INTO FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK(lock_name, revision)
SELECT 'PUBLICATION', 0
WHERE NOT EXISTS (
  SELECT 1 FROM FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK
  WHERE lock_name = 'PUBLICATION'
);

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_BEGIN_TIER1_REVIEW_BATCH(P_MANIFEST_JSON VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(sql, binds) { return snowflake.createStatement({sqlText: sql, binds: binds || []}).execute(); }
function one(sql, binds) { var r=q(sql,binds); if (!r.next()) throw 'MISSING_ROW'; return r.getColumnValue(1); }
function lock() {
  q("UPDATE FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK SET revision=revision+1 WHERE lock_name='PUBLICATION'");
  if (one("SELECT COUNT(*) FROM FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK WHERE lock_name='PUBLICATION'") !== 1) throw 'INVALID_LOCK';
}
if (typeof P_MANIFEST_JSON !== 'string' || P_MANIFEST_JSON.length > 8192) throw 'INVALID_MANIFEST';
var m=JSON.parse(P_MANIFEST_JSON);
var pinned={batch_id:'tier1-review-priority-744b2933bae43718',
 output_sha256:'3c05f9d6e0a150c29be3bcc6a0c20233cc8f1171dd0ec91ad82c8f68e1c35b41',
 source_commit:'c6bb8a0f48ede70f332513c1b5843f35988949f1',
 generated_at_utc:'2026-10-06T05:34:52Z',
 release_id:'governed-2026-09-17-unknown-coverage',
 bundle_sha256:'55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233',
 row_count:3144, schema:'tier1-persisted-output-v1'};
if (!m || Object.keys(m).length !== Object.keys(pinned).length+2) throw 'INVALID_MANIFEST_FIELDS';
for (var k in pinned) if (m[k] !== pinned[k]) throw 'WRONG_MANIFEST_LINEAGE';
if (!m.tier_counts || Object.keys(m.tier_counts).length!==3 ||
    m.tier_counts.HIGH!==315 || m.tier_counts.MEDIUM!==628 || m.tier_counts.LOW!==2201 ||
    !m.sufficiency_counts || Object.keys(m.sufficiency_counts).length!==2 ||
    m.sufficiency_counts.SUFFICIENT!==651 ||
    m.sufficiency_counts.INSUFFICIENT!==2493) throw 'WRONG_MANIFEST_COUNTS';
try {
 q('BEGIN TRANSACTION'); lock();
 var r=q('SELECT output_sha256, state FROM FEATURE_STORE.TIER1_REVIEW_BATCHES WHERE batch_id=?',[m.batch_id]);
 if (r.next()) {
   var existingDigest=r.getColumnValue(1), existingState=r.getColumnValue(2);
   if (existingDigest!==m.output_sha256 || r.next()) throw 'CHANGED_DIGEST_REPLAY';
   q('COMMIT'); return {state:existingState,batch_id:m.batch_id,replay:true};
 }
 q(`INSERT INTO FEATURE_STORE.TIER1_REVIEW_BATCHES
    (batch_id,output_sha256,source_commit,generated_at_utc,release_id,bundle_sha256,
     model_version,feature_set_version,evaluation_version,tier_policy_version,expected_rows,state)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,'STAGING')`,
   [m.batch_id,m.output_sha256,m.source_commit,m.generated_at_utc,m.release_id,m.bundle_sha256,
    'tier1-statistical-reference-v1','tier1-county-features-v1','tier1-selection-evaluation-v1',
    'tier1-review-percentile-v1',3144]);
 q('COMMIT'); return {state:'STAGING',batch_id:m.batch_id};
} catch(e) { q('ROLLBACK'); throw e; }
$$;

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_STAGE_TIER1_REVIEW_ROWS(P_BATCH_ID VARCHAR, P_ROWS_JSON VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(sql, binds) { return snowflake.createStatement({sqlText: sql, binds: binds || []}).execute(); }
function one(sql, binds) { var r=q(sql,binds); if (!r.next()) throw 'MISSING_ROW'; return r.getColumnValue(1); }
if (P_BATCH_ID!=='tier1-review-priority-744b2933bae43718' ||
    typeof P_ROWS_JSON!=='string' || P_ROWS_JSON.length>900000) throw 'INVALID_STAGE_REQUEST';
var rows=JSON.parse(P_ROWS_JSON);
if (!Array.isArray(rows) || rows.length<1 || rows.length>250) throw 'INVALID_CHUNK_SIZE';
var seen={};
for (var i=0;i<rows.length;i++) {
 if (typeof rows[i]!=='string' || rows[i].length>4096) throw 'INVALID_ROW_SIZE';
 var row=JSON.parse(rows[i]);
 if (!row || !/^[0-9]{5}$/.test(row.county_fips) || seen[row.county_fips]) throw 'DUPLICATE_OR_INVALID_FIPS';
 seen[row.county_fips]=true;
}
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK SET revision=revision+1 WHERE lock_name='PUBLICATION'");
 if (one("SELECT COUNT(*) FROM FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK WHERE lock_name='PUBLICATION'")!==1) throw 'INVALID_LOCK';
 if (one('SELECT COUNT(*) FROM FEATURE_STORE.TIER1_REVIEW_BATCHES WHERE batch_id=? AND state=\'STAGING\'',[P_BATCH_ID])!==1) throw 'BATCH_NOT_STAGING';
 var existing=q('SELECT county_fips, row_json FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?',[P_BATCH_ID]);
 var known={}; while(existing.next()) known[existing.getColumnValue(1)]=existing.getColumnValue(2);
 var pending=[];
 for (var j=0;j<rows.length;j++) {
   var fips=JSON.parse(rows[j]).county_fips;
   if (known[fips]!==undefined) {
     if (known[fips]!==rows[j]) throw 'CHANGED_ROW_REPLAY';
   } else pending.push(rows[j]);
 }
 if (pending.length) {
   q(`INSERT INTO FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS(batch_id,county_fips,row_json)
      SELECT ?, TRY_PARSE_JSON(value::VARCHAR):county_fips::VARCHAR, value::VARCHAR
      FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(?)))`,[P_BATCH_ID,JSON.stringify(pending)]);
 }
 q('COMMIT'); return {accepted:rows.length,inserted:pending.length};
} catch(e) { q('ROLLBACK'); throw e; }
$$;

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_FINALIZE_TIER1_REVIEW_BATCH(P_BATCH_ID VARCHAR, P_OUTPUT_SHA256 VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(sql, binds) { return snowflake.createStatement({sqlText: sql, binds: binds || []}).execute(); }
function one(sql, binds) { var r=q(sql,binds); if (!r.next()) throw 'MISSING_ROW'; return r.getColumnValue(1); }
if (P_BATCH_ID!=='tier1-review-priority-744b2933bae43718' ||
    P_OUTPUT_SHA256!=='3c05f9d6e0a150c29be3bcc6a0c20233cc8f1171dd0ec91ad82c8f68e1c35b41') throw 'WRONG_BATCH';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK SET revision=revision+1 WHERE lock_name='PUBLICATION'");
 if (one("SELECT COUNT(*) FROM FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK WHERE lock_name='PUBLICATION'")!==1) throw 'INVALID_LOCK';
 var batch=q('SELECT output_sha256,state,release_id,bundle_sha256 FROM FEATURE_STORE.TIER1_REVIEW_BATCHES WHERE batch_id=?',[P_BATCH_ID]);
 if (!batch.next()) throw 'NO_MANIFEST';
 var digest=batch.getColumnValue(1), state=batch.getColumnValue(2);
 if (batch.next() || digest!==P_OUTPUT_SHA256) throw 'CHANGED_DIGEST_REPLAY';
 if (state==='APPROVED') { q('COMMIT'); return {state:'APPROVED',batch_id:P_BATCH_ID,replay:true}; }
 if (state!=='STAGING') throw 'INVALID_BATCH_STATE';
 if (one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES
          WHERE release_id='governed-2026-09-17-unknown-coverage'
            AND bundle_sha256='55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233'
            AND status='PUBLISHED'`)!==1) throw 'WRONG_GOVERNED_RELEASE';
 if (one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
          WHERE release_id='governed-2026-09-17-unknown-coverage'`)!==3144) throw 'WRONG_GOVERNED_POPULATION';
 if (one(`SELECT COUNT(*) FROM (
          SELECT fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
          WHERE release_id='governed-2026-09-17-unknown-coverage'
          GROUP BY fips HAVING COUNT(*)<>1)`)!==0) throw 'DUPLICATE_GOVERNED_FIPS';
 if (one('SELECT COUNT(*) FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?',[P_BATCH_ID])!==3144) throw 'INCOMPLETE_BATCH';
 if (one(`SELECT COUNT(*) FROM (
          SELECT county_fips FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS
          WHERE batch_id=? GROUP BY county_fips HAVING COUNT(*)<>1)`,[P_BATCH_ID])!==0) throw 'DUPLICATE_FIPS';
 if (one(`SELECT COUNT(*) FROM (
          SELECT county_fips FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?
          EXCEPT SELECT fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
          WHERE release_id='governed-2026-09-17-unknown-coverage')`,[P_BATCH_ID])!==0 ||
     one(`SELECT COUNT(*) FROM (
          SELECT fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
          WHERE release_id='governed-2026-09-17-unknown-coverage'
          EXCEPT SELECT county_fips FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS
          WHERE batch_id=?)`,[P_BATCH_ID])!==0) throw 'FIPS_SET_MISMATCH';
 var invalid=one(`WITH parsed AS (
   SELECT county_fips, TRY_PARSE_JSON(row_json) AS r
   FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?)
   SELECT COUNT(*) FROM parsed WHERE r IS NULL OR TYPEOF(r)<>'OBJECT' OR
     ARRAY_SIZE(OBJECT_KEYS(r))<>20 OR
     COALESCE(r:county_fips::VARCHAR,'')<>county_fips OR
     COALESCE(r:model_version::VARCHAR,'')<>'tier1-statistical-reference-v1' OR
     COALESCE(r:feature_set_version::VARCHAR,'')<>'tier1-county-features-v1' OR
     COALESCE(r:evaluation_version::VARCHAR,'')<>'tier1-selection-evaluation-v1' OR
     COALESCE(r:tier_policy_version::VARCHAR,'')<>'tier1-review-percentile-v1' OR
     COALESCE(r:prediction_batch_version::VARCHAR,'')<>'tier1-review-priority-744b2933bae43718' OR
     COALESCE(r:run_id::VARCHAR,'')<>'tier1-review-priority-744b2933bae43718' OR
     COALESCE(r:release_id::VARCHAR,'')<>'governed-2026-09-17-unknown-coverage' OR
     COALESCE(r:bundle_sha256::VARCHAR,'')<>'55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233' OR
     COALESCE(r:source_commit::VARCHAR,'')<>'c6bb8a0f48ede70f332513c1b5843f35988949f1' OR
     COALESCE(r:generated_at_utc::VARCHAR,'')<>'2026-10-06T05:34:52Z' OR
     COALESCE(r:limitation_ref::VARCHAR,'')<>'docs/contracts/tier1-persisted-output-v1.md' OR
     COALESCE(r:priority_tier::VARCHAR,'') NOT IN ('HIGH','MEDIUM','LOW') OR
     COALESCE(r:evidence_sufficiency::VARCHAR,'') NOT IN ('SUFFICIENT','INSUFFICIENT') OR
     COALESCE(r:feature_evidence_state::VARCHAR,'') NOT IN ('OBSERVED','PARTIAL') OR
     (r:evidence_sufficiency::VARCHAR='SUFFICIENT' AND r:feature_evidence_state::VARCHAR<>'OBSERVED') OR
     (r:evidence_sufficiency::VARCHAR='INSUFFICIENT' AND r:feature_evidence_state::VARCHAR<>'PARTIAL') OR
     (r:evidence_sufficiency::VARCHAR='NOT_ESTIMABLE' AND
      (r:raw_model_score IS NOT NULL OR r:priority_percentile IS NOT NULL OR
       r:priority_tier IS NOT NULL)) OR
     r:raw_model_score IS NULL OR r:priority_percentile IS NULL OR
     TRY_TO_DOUBLE(r:raw_model_score::VARCHAR) IS NULL OR
     COALESCE(TRY_TO_DOUBLE(r:priority_percentile::VARCHAR),-1) NOT BETWEEN 0 AND 100 OR
     (TRY_TO_DOUBLE(r:priority_percentile::VARCHAR)>=90 AND r:priority_tier::VARCHAR<>'HIGH') OR
     (TRY_TO_DOUBLE(r:priority_percentile::VARCHAR)>=70 AND TRY_TO_DOUBLE(r:priority_percentile::VARCHAR)<90 AND r:priority_tier::VARCHAR<>'MEDIUM') OR
     (TRY_TO_DOUBLE(r:priority_percentile::VARCHAR)<70 AND r:priority_tier::VARCHAR<>'LOW') OR
     NULLIF(r:human_evidence_state::VARCHAR,'') IS NULL OR
     NULLIF(r:pathogen_evidence_state::VARCHAR,'') IS NULL OR
     TYPEOF(r:reasons)<>'ARRAY' OR ARRAY_SIZE(r:reasons) NOT BETWEEN 2 AND 3`,[P_BATCH_ID]);
 if (invalid!==0) throw 'INVALID_COUNTY_ROWS';
 var reasons=one(`SELECT COUNT(*) FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS o,
      LATERAL FLATTEN(INPUT=>TRY_PARSE_JSON(o.row_json):reasons) f
      WHERE o.batch_id=? AND (
      TYPEOF(f.value)<>'OBJECT' OR ARRAY_SIZE(OBJECT_KEYS(f.value))<>2 OR
      NULLIF(f.value:code::VARCHAR,'') IS NULL OR
      f.value:code::VARCHAR NOT IN ('PUBLISHED_HUMAN_FLOOR','NO_COUNTY_HUMAN_RECORD',
        'PATHOGEN_PRESENT','PATHOGEN_NO_RECORDS','PATHOGEN_UNKNOWN','SVI_CONTEXT_DIFFERENCE') OR
      NULLIF(f.value:text::VARCHAR,'') IS NULL OR LENGTH(f.value:text::VARCHAR)>180 OR
      REGEXP_LIKE(LOWER(f.value:text::VARCHAR),'.*(caused|risk|outbreak|incidence).*'))`,[P_BATCH_ID]);
 if (reasons!==0) throw 'INVALID_REASONS';
 var counts=q(`SELECT r:priority_tier::VARCHAR, r:evidence_sufficiency::VARCHAR, COUNT(*)
      FROM (SELECT TRY_PARSE_JSON(row_json) r FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?)
      GROUP BY 1,2`,[P_BATCH_ID]);
 var tiers={HIGH:0,MEDIUM:0,LOW:0}, suff={SUFFICIENT:0,INSUFFICIENT:0};
 while(counts.next()) { var n=counts.getColumnValue(3); tiers[counts.getColumnValue(1)]+=n; suff[counts.getColumnValue(2)]+=n; }
 if (tiers.HIGH!==315 || tiers.MEDIUM!==628 || tiers.LOW!==2201 ||
     suff.SUFFICIENT!==651 || suff.INSUFFICIENT!==2493) throw 'PINNED_COUNT_DRIFT';
 var computed=one(`SELECT LOWER(SHA2('[' || LISTAGG(row_json, ',') WITHIN GROUP (ORDER BY county_fips) || ']',256))
      FROM FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS WHERE batch_id=?`,[P_BATCH_ID]);
 if (computed!==digest) throw 'DIGEST_MISMATCH';
 q("UPDATE FEATURE_STORE.TIER1_REVIEW_BATCHES SET state='APPROVED',approved_at=CURRENT_TIMESTAMP() WHERE batch_id=? AND state='STAGING'",[P_BATCH_ID]);
 q("UPDATE FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH SET batch_id=?,activated_at=CURRENT_TIMESTAMP() WHERE pointer_key='TIER1_COUNTY_REVIEW'",[P_BATCH_ID]);
 if (one("SELECT COUNT(*) FROM FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH WHERE pointer_key='TIER1_COUNTY_REVIEW' AND batch_id=?",[P_BATCH_ID])!==1) throw 'INVALID_POINTER';
 q('COMMIT'); return {state:'APPROVED',batch_id:P_BATCH_ID,output_sha256:digest,replay:false};
} catch(e) { q('ROLLBACK'); throw e; }
$$;

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V AS
SELECT o.county_fips,
  TRY_PARSE_JSON(o.row_json):priority_tier::VARCHAR AS priority_tier,
  TRY_PARSE_JSON(o.row_json):priority_percentile::DOUBLE AS priority_percentile,
  TRY_PARSE_JSON(o.row_json):raw_model_score::DOUBLE AS raw_model_score,
  TRY_PARSE_JSON(o.row_json):evidence_sufficiency::VARCHAR AS evidence_sufficiency,
  TRY_PARSE_JSON(o.row_json):model_version::VARCHAR AS model_version,
  TRY_PARSE_JSON(o.row_json):feature_set_version::VARCHAR AS feature_set_version,
  TRY_PARSE_JSON(o.row_json):evaluation_version::VARCHAR AS evaluation_version,
  TRY_PARSE_JSON(o.row_json):tier_policy_version::VARCHAR AS tier_policy_version,
  TRY_PARSE_JSON(o.row_json):prediction_batch_version::VARCHAR AS prediction_batch_version,
  TRY_PARSE_JSON(o.row_json):run_id::VARCHAR AS run_id,
  TRY_PARSE_JSON(o.row_json):release_id::VARCHAR AS release_id,
  TRY_PARSE_JSON(o.row_json):bundle_sha256::VARCHAR AS bundle_sha256,
  TRY_PARSE_JSON(o.row_json):source_commit::VARCHAR AS source_commit,
  TRY_PARSE_JSON(o.row_json):generated_at_utc::VARCHAR AS generated_at_utc,
  TRY_PARSE_JSON(o.row_json):human_evidence_state::VARCHAR AS human_evidence_state,
  TRY_PARSE_JSON(o.row_json):pathogen_evidence_state::VARCHAR AS pathogen_evidence_state,
  TRY_PARSE_JSON(o.row_json):feature_evidence_state::VARCHAR AS feature_evidence_state,
  TRY_PARSE_JSON(o.row_json):reasons AS reasons,
  TRY_PARSE_JSON(o.row_json):limitation_ref::VARCHAR AS limitation_ref
FROM FEATURE_STORE.TIER1_REVIEW_ACTIVE_BATCH p
JOIN FEATURE_STORE.TIER1_REVIEW_BATCHES b ON b.batch_id=p.batch_id AND b.state='APPROVED'
JOIN FEATURE_STORE.TIER1_COUNTY_REVIEW_OUTPUTS o ON o.batch_id=b.batch_id
WHERE p.pointer_key='TIER1_COUNTY_REVIEW';

GRANT SELECT ON VIEW PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V TO ROLE OH_LYME_DEV_READ;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_BEGIN_TIER1_REVIEW_BATCH(VARCHAR) TO ROLE OH_LYME_DEV_ML_PUBLISHER;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_STAGE_TIER1_REVIEW_ROWS(VARCHAR,VARCHAR) TO ROLE OH_LYME_DEV_ML_PUBLISHER;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_FINALIZE_TIER1_REVIEW_BATCH(VARCHAR,VARCHAR) TO ROLE OH_LYME_DEV_ML_PUBLISHER;
