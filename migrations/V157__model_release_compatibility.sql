-- DATA698. No compatibility is approved by installing this migration.
USE DATABASE {{ DATABASE }};
CREATE TABLE IF NOT EXISTS FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY (
  decision_id VARCHAR NOT NULL, artifact_id VARCHAR NOT NULL, batch_id VARCHAR NOT NULL,
  input_release_id VARCHAR NOT NULL, input_bundle_sha256 VARCHAR(64) NOT NULL,
  target_release_id VARCHAR NOT NULL, target_bundle_sha256 VARCHAR(64) NOT NULL,
  evidence_reference VARCHAR NOT NULL, approved_by VARCHAR NOT NULL,
  approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS FEATURE_STORE.MODEL_COMPATIBILITY_LOCK (
  lock_key VARCHAR NOT NULL, revision NUMBER NOT NULL
);
INSERT INTO FEATURE_STORE.MODEL_COMPATIBILITY_LOCK
SELECT 'MODEL_RELEASE',0 WHERE NOT EXISTS (
 SELECT 1 FROM FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE');

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(
 P_ARTIFACT VARCHAR,P_TARGET_RELEASE VARCHAR, P_TARGET_BUNDLE VARCHAR, P_DECISION VARCHAR, P_EVIDENCE VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b) { return snowflake.createStatement({sqlText:s,binds:b||[]}).execute(); }
function one(s,b) { var r=q(s,b); if(!r.next()) throw 'MISSING_EVIDENCE'; return r.getColumnValue(1); }
if (!P_DECISION || !P_EVIDENCE || P_EVIDENCE.length<12 || !/^[0-9a-f]{64}$/.test(P_TARGET_BUNDLE)) throw 'INVALID_DECISION';
var source='governed-2026-09-18-unknown-coverage';
var sourceBundle='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026';
var batch='tier1-review-priority-5536b5caad95cf47';
var columns='fips,human_status,case_count_floor_2023,tick_status,scapularis_status,pacificus_status,burgdorferi_status,svi_percentile,rucc_2023';
var slots="'human','pathogen','context_svi','context_rucc','tick'";
if(P_ARTIFACT==='surveillance-situation-four-state'||P_ARTIFACT==='surveillance-situation-tick-pathogen') {
 source='governed-2026-10-15-january-climate-prod';
 sourceBundle='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d';
 batch='surveillance-situation-batch';
 columns='fips,state,population,scapularis_status,pacificus_status,burgdorferi_status';
 slots="'pathogen','context_svi','tick'";
 if(P_ARTIFACT==='surveillance-situation-four-state') {columns+=',human_status';slots+=",'human'";}
}else if(P_ARTIFACT!=='tier1')throw 'UNSUPPORTED_MODEL_CONTRACT';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1) throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_TARGET_RELEASE,P_TARGET_BUNDLE])!==1 ||
    one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('PUBLISHED','RETIRED')`,[source,sourceBundle])!==1) throw 'WRONG_RELEASE';
 // The complete feature/evidence projection used by ML tier1-county-features-v2,
 // including vector and RUCC context, must be identical. EXCEPT is bidirectional.
 for(var i=0;i<2;i++) {
  var a=i===0?source:P_TARGET_RELEASE, b=i===0?P_TARGET_RELEASE:source;
  if(one(`SELECT COUNT(*) FROM (SELECT ${columns} FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=? MINUS SELECT ${columns} FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?)`,[a,b])!==0) throw 'CHANGED_MODEL_INPUT';
 }
 for(var j=0;j<2;j++) {
  if(one('SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?',[j===0?source:P_TARGET_RELEASE])!==3144 ||
     one('SELECT COUNT(DISTINCT fips) FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?',[j===0?source:P_TARGET_RELEASE])!==3144) throw 'CHANGED_MEMBERSHIP';
 }
 // Same values alone are insufficient: compare original source identity,
 // version, run, artifact and descriptive attribution for every predictor source.
 var lineage='source_key,resource_key,source_id,dataset_id,source_version_id,ingestion_run_id,artifact_id,vintage,note,source_url,label';
 for(var k=0;k<2;k++) {
  var a=k===0?source:P_TARGET_RELEASE,b=k===0?P_TARGET_RELEASE:source;
  if(one(`SELECT COUNT(*) FROM (SELECT ${lineage} FROM PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=? AND source_key IN (${slots}) MINUS SELECT ${lineage} FROM PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=? AND source_key IN (${slots}))`,[a,b])!==0) throw 'CHANGED_SCIENTIFIC_LINEAGE';
  if(one(`SELECT COUNT(*) FROM (
   SELECT f.value:source_key::VARCHAR,f.value:artifact_sha256::VARCHAR,f.value:definition_version::VARCHAR,TO_JSON(f.value:field_map)
   FROM PRESENTATION.SEMANTIC_RELEASES r,LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f WHERE r.release_id=? AND f.value:source_key::VARCHAR IN (${slots})
   MINUS SELECT f.value:source_key::VARCHAR,f.value:artifact_sha256::VARCHAR,f.value:definition_version::VARCHAR,TO_JSON(f.value:field_map)
   FROM PRESENTATION.SEMANTIC_RELEASES r,LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f WHERE r.release_id=? AND f.value:source_key::VARCHAR IN (${slots}))`,[a,b])!==0)throw 'CHANGED_SOURCE_MAPPING_OR_HASH';
 }
 var existing=q('SELECT target_release_id,target_bundle_sha256,evidence_reference,artifact_id,batch_id FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY WHERE decision_id=?',[P_DECISION]);
 if(existing.next()) {
  if(existing.getColumnValue(1)!==P_TARGET_RELEASE || existing.getColumnValue(2)!==P_TARGET_BUNDLE || existing.getColumnValue(3)!==P_EVIDENCE || existing.getColumnValue(4)!==P_ARTIFACT || existing.getColumnValue(5)!==batch || existing.next()) throw 'CHANGED_DECISION_REPLAY';
  q('COMMIT'); return {decision_id:P_DECISION,replay:true};
 }
 q(`INSERT INTO FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY(decision_id,artifact_id,batch_id,input_release_id,input_bundle_sha256,target_release_id,target_bundle_sha256,evidence_reference,approved_by)
 SELECT ?,?,?,?,?,?,?,?,CURRENT_USER()`,[P_DECISION,P_ARTIFACT,batch,source,sourceBundle,P_TARGET_RELEASE,P_TARGET_BUNDLE,P_EVIDENCE]);
 q('COMMIT'); return {decision_id:P_DECISION,replay:false};
} catch(e) {q('ROLLBACK');throw e;}
$$;
-- Human owner only. Ingestion and ML publishers cannot approve compatibility.
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(VARCHAR,VARCHAR,VARCHAR,VARCHAR,VARCHAR)
 TO ROLE OH_LYME_{{ ENV }}_OWNER;
CREATE OR REPLACE VIEW PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V AS
SELECT decision_id,artifact_id,batch_id,input_release_id,input_bundle_sha256,
 target_release_id,target_bundle_sha256,evidence_reference,approved_by,approved_at
FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY;
GRANT SELECT ON VIEW PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V TO ROLE OH_LYME_{{ ENV }}_READ;

-- Explicit degraded-release authorization is separate from the candidate's
-- proposed inventory. Only a human owner can record this immutable decision.
CREATE TABLE IF NOT EXISTS FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS (
 decision_id VARCHAR NOT NULL,target_release_id VARCHAR NOT NULL,
 target_bundle_sha256 VARCHAR(64) NOT NULL,artifact_id VARCHAR NOT NULL,
 expected_rows NUMBER NOT NULL,reason VARCHAR NOT NULL,
 consumer_implications VARCHAR NOT NULL,rollback_plan VARCHAR NOT NULL,
 approved_by VARCHAR NOT NULL,approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_APPROVE_RELEASE_COMPLETENESS_EXCEPTION(
 P_DECISION VARCHAR,P_RELEASE VARCHAR,P_BUNDLE VARCHAR,P_ARTIFACT VARCHAR,P_ROWS FLOAT,
 P_REASON VARCHAR,P_IMPLICATIONS VARCHAR,P_ROLLBACK VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if(!P_DECISION||!P_ARTIFACT||!Number.isInteger(P_ROWS)||P_ROWS<0||!P_REASON||P_REASON.length<20||!P_IMPLICATIONS||P_IMPLICATIONS.length<20||!P_ROLLBACK||P_ROLLBACK.length<20)throw 'INVALID_EXCEPTION';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1)throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_RELEASE,P_BUNDLE])!==1)throw 'EXCEPTION_REQUIRES_EXACT_RETAINED_RELEASE';
 var existing=q('SELECT target_release_id,target_bundle_sha256,artifact_id,expected_rows,reason,consumer_implications,rollback_plan FROM FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS WHERE decision_id=?',[P_DECISION]);
 var values=[P_RELEASE,P_BUNDLE,P_ARTIFACT,P_ROWS,P_REASON,P_IMPLICATIONS,P_ROLLBACK];
 if(existing.next()) {
  for(var i=0;i<values.length;i++)if(existing.getColumnValue(i+1)!==values[i])throw 'CHANGED_EXCEPTION_REPLAY';
  if(existing.next())throw 'DUPLICATE_EXCEPTION';q('COMMIT');return {replay:true};
 }
 q(`INSERT INTO FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS(decision_id,target_release_id,target_bundle_sha256,artifact_id,expected_rows,reason,consumer_implications,rollback_plan,approved_by) SELECT ?,?,?,?,?,?,?,?,CURRENT_USER()`,[P_DECISION].concat(values));
 q('COMMIT');return {decision_id:P_DECISION,replay:false};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_APPROVE_RELEASE_COMPLETENESS_EXCEPTION(VARCHAR,VARCHAR,VARCHAR,VARCHAR,FLOAT,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_OWNER;
CREATE OR REPLACE VIEW PRESENTATION.RELEASE_COMPLETENESS_EXCEPTIONS_V AS
SELECT * FROM FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS;
GRANT SELECT ON VIEW PRESENTATION.RELEASE_COMPLETENESS_EXCEPTIONS_V TO ROLE OH_LYME_{{ ENV }}_READ;

-- Forward admission preserves existing immutable release manifests and makes
-- legacy rollback possible only with explicit completeness/degradation review.
CREATE TABLE IF NOT EXISTS FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS (
 release_id VARCHAR NOT NULL,bundle_sha256 VARCHAR(64) NOT NULL,
 manifest_json VARCHAR NOT NULL,manifest_sha256 VARCHAR(64) NOT NULL,
 evidence_reference VARCHAR NOT NULL,approved_by VARCHAR NOT NULL,
 approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_ADMIT_RELEASE_COMPLETENESS(
 P_RELEASE VARCHAR,P_BUNDLE VARCHAR,P_MANIFEST VARCHAR,P_EVIDENCE VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if(!P_EVIDENCE||P_EVIDENCE.length<12||!P_MANIFEST||P_MANIFEST.length>100000)throw 'INVALID_ADMISSION';
var m=JSON.parse(P_MANIFEST);if(m.schema!=='atlas-release-completeness/v1'||!Array.isArray(m.artifacts)||!Array.isArray(m.views))throw 'INVALID_COMPLETENESS_MANIFEST';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1)throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_RELEASE,P_BUNDLE])!==1)throw 'WRONG_RELEASE';
 var existing=q('SELECT manifest_json,evidence_reference FROM FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS WHERE release_id=? AND bundle_sha256=?',[P_RELEASE,P_BUNDLE]);
 if(existing.next()) {
  if(existing.getColumnValue(1)!==P_MANIFEST||existing.getColumnValue(2)!==P_EVIDENCE||existing.next())throw 'CHANGED_COMPLETENESS_REPLAY';q('COMMIT');return {replay:true};
 }
 q(`INSERT INTO FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS(release_id,bundle_sha256,manifest_json,manifest_sha256,evidence_reference,approved_by) SELECT ?,?,?,LOWER(SHA2(?,256)),?,CURRENT_USER()`,[P_RELEASE,P_BUNDLE,P_MANIFEST,P_MANIFEST,P_EVIDENCE]);
 q('COMMIT');return {replay:false};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_ADMIT_RELEASE_COMPLETENESS(VARCHAR,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_OWNER;
CREATE OR REPLACE VIEW PRESENTATION.RELEASE_COMPLETENESS_ADMISSIONS_V AS
SELECT * FROM FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS;
GRANT SELECT ON VIEW PRESENTATION.RELEASE_COMPLETENESS_ADMISSIONS_V TO ROLE OH_LYME_{{ ENV }}_READ;
