-- UNAPPROVED FIXTURE RENDERING. DO NOT EXECUTE.
-- DATA698. No compatibility is approved by installing this migration.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_DEV;
CREATE TABLE IF NOT EXISTS RI706_FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY (
  decision_id VARCHAR NOT NULL, artifact_id VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
  batch_id VARCHAR NOT NULL,batch_version VARCHAR NOT NULL,
  input_release_id VARCHAR NOT NULL, input_bundle_sha256 VARCHAR(64) NOT NULL,
  target_release_id VARCHAR NOT NULL, target_bundle_sha256 VARCHAR(64) NOT NULL,
  evidence_reference VARCHAR NOT NULL, approved_by VARCHAR NOT NULL,
  approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK (
  lock_key VARCHAR NOT NULL, revision NUMBER NOT NULL
);
INSERT INTO RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK
SELECT 'MODEL_RELEASE',0 WHERE NOT EXISTS (
 SELECT 1 FROM RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE');

CREATE OR REPLACE PROCEDURE RI706_FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(
 P_ARTIFACT VARCHAR,P_TARGET_RELEASE VARCHAR, P_TARGET_BUNDLE VARCHAR, P_DECISION VARCHAR, P_EVIDENCE VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b) { return snowflake.createStatement({sqlText:s,binds:b||[]}).execute(); }
function one(s,b) { var r=q(s,b); if(!r.next()) throw 'MISSING_EVIDENCE'; return r.getColumnValue(1); }
if (!P_DECISION || !P_EVIDENCE || P_EVIDENCE.length<12 || !/^[0-9a-f]{64}$/.test(P_TARGET_BUNDLE)) throw 'INVALID_DECISION';
var source='governed-2026-09-18-unknown-coverage';
var sourceBundle='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026';
var batch='tier1-review-priority-5536b5caad95cf47';
var modelVersion='tier1-statistical-reference-v1',batchVersion=batch;
var columns='fips,human_status,case_count_floor_2023,tick_status,scapularis_status,pacificus_status,burgdorferi_status,svi_percentile,rucc_2023';
var slots="'human','pathogen','context_svi','context_rucc','tick'";
if(P_ARTIFACT==='surveillance-situation-four-state'||P_ARTIFACT==='surveillance-situation-tick-pathogen') {
 source='governed-2026-10-15-january-climate-prod';
 sourceBundle='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d';
 batch='surveillance-situation-batch';
 modelVersion='v1';batchVersion='v1';
 columns='fips,state,population,scapularis_status,pacificus_status,burgdorferi_status';
 slots="'pathogen','context_svi','tick'";
 if(P_ARTIFACT==='surveillance-situation-four-state') {columns+=',human_status';slots+=",'human'";}
}else if(P_ARTIFACT!=='tier1')throw 'UNSUPPORTED_MODEL_CONTRACT';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1) throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_TARGET_RELEASE,P_TARGET_BUNDLE])!==1 ||
    one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('PUBLISHED','RETIRED')`,[source,sourceBundle])!==1) throw 'WRONG_RELEASE';
 // The complete feature/evidence projection used by ML tier1-county-features-v2,
 // including vector and RUCC context, must be identical. EXCEPT is bidirectional.
 for(var i=0;i<2;i++) {
  var a=i===0?source:P_TARGET_RELEASE, b=i===0?P_TARGET_RELEASE:source;
  if(one(`SELECT COUNT(*) FROM (SELECT ${columns} FROM RI706_PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=? MINUS SELECT ${columns} FROM RI706_PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?)`,[a,b])!==0) throw 'CHANGED_MODEL_INPUT';
 }
 for(var j=0;j<2;j++) {
  if(one('SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?',[j===0?source:P_TARGET_RELEASE])!==3144 ||
     one('SELECT COUNT(DISTINCT fips) FROM RI706_PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=?',[j===0?source:P_TARGET_RELEASE])!==3144) throw 'CHANGED_MEMBERSHIP';
 }
 // Same values alone are insufficient: compare original source identity,
 // version, run, artifact and descriptive attribution for every predictor source.
 var lineage='source_key,resource_key,source_id,dataset_id,source_version_id,ingestion_run_id,artifact_id,vintage,note,source_url,label';
 for(var k=0;k<2;k++) {
  var a=k===0?source:P_TARGET_RELEASE,b=k===0?P_TARGET_RELEASE:source;
  if(one(`SELECT COUNT(*) FROM (SELECT ${lineage} FROM RI706_PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=? AND source_key IN (${slots}) MINUS SELECT ${lineage} FROM RI706_PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=? AND source_key IN (${slots}))`,[a,b])!==0) throw 'CHANGED_SCIENTIFIC_LINEAGE';
  if(one(`SELECT COUNT(*) FROM (
   SELECT f.value:source_key::VARCHAR,f.value:artifact_sha256::VARCHAR,f.value:definition_version::VARCHAR,f.value:field_map
   FROM RI706_PRESENTATION.SEMANTIC_RELEASES r,LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f WHERE r.release_id=? AND f.value:source_key::VARCHAR IN (${slots})
   MINUS SELECT f.value:source_key::VARCHAR,f.value:artifact_sha256::VARCHAR,f.value:definition_version::VARCHAR,f.value:field_map
   FROM RI706_PRESENTATION.SEMANTIC_RELEASES r,LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f WHERE r.release_id=? AND f.value:source_key::VARCHAR IN (${slots}))`,[a,b])!==0)throw 'CHANGED_SOURCE_MAPPING_OR_HASH';
 }
 // Compare full observation lineage, retaining multiplicities; equal predictors
 // or source-level pins cannot authorize changed county-record provenance.
 var rowLineage='fips,measure_id,temporal_window,source_key,source_version_id,ingestion_run_id,artifact_id,source_record_id,source_row_hash';
 var partitions=q("SELECT DISTINCT SUBSTR(fips,1,2) FROM RI706_PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id=? ORDER BY 1",[source]);
 var partitionCount=0,comparedRows=0;
 while(partitions.next()) {
  var state=partitions.getColumnValue(1);partitionCount++;
  if(partitionCount>60||!/^[0-9]{2}$/.test(state))throw 'INVALID_LINEAGE_PARTITION';
  for(var direction=0;direction<2;direction++) {
   var left=direction===0?source:P_TARGET_RELEASE,right=direction===0?P_TARGET_RELEASE:source;
   if(one(`SELECT COUNT(*) FROM (
    SELECT ${rowLineage},COUNT(*) AS multiplicity FROM RI706_PRESENTATION.SEMANTIC_OBSERVATIONS
    WHERE release_id=? AND source_key IN (${slots}) AND SUBSTR(fips,1,2)=? GROUP BY ${rowLineage}
    MINUS SELECT ${rowLineage},COUNT(*) AS multiplicity FROM RI706_PRESENTATION.SEMANTIC_OBSERVATIONS
    WHERE release_id=? AND source_key IN (${slots}) AND SUBSTR(fips,1,2)=? GROUP BY ${rowLineage})`,[left,state,right,state])!==0)throw 'CHANGED_OBSERVATION_LINEAGE';
  }
  comparedRows+=one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id=? AND source_key IN (${slots}) AND SUBSTR(fips,1,2)=?`,[source,state]);
 }
 if(partitionCount===0||comparedRows===0)throw 'MISSING_OBSERVATION_LINEAGE';
 var expectedSources=slots.split(',').length;
 for(var side=0;side<2;side++) {
  var identity=side===0?source:P_TARGET_RELEASE;
  if(one(`SELECT COUNT(DISTINCT source_key) FROM RI706_PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=? AND source_key IN (${slots})`,[identity])!==expectedSources)throw 'MISSING_SOURCE_LINEAGE';
  if(one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_RELEASES r,LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f WHERE r.release_id=? AND f.value:source_key::VARCHAR IN (${slots})`,[identity])!==expectedSources)throw 'MISSING_SOURCE_MAPPING';
 }
 var existing=q('SELECT target_release_id,target_bundle_sha256,evidence_reference,artifact_id,batch_id,model_version,batch_version FROM RI706_FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY WHERE decision_id=?',[P_DECISION]);
 if(existing.next()) {
  if(existing.getColumnValue(1)!==P_TARGET_RELEASE || existing.getColumnValue(2)!==P_TARGET_BUNDLE || existing.getColumnValue(3)!==P_EVIDENCE || existing.getColumnValue(4)!==P_ARTIFACT || existing.getColumnValue(5)!==batch || existing.getColumnValue(6)!==modelVersion || existing.getColumnValue(7)!==batchVersion || existing.next()) throw 'CHANGED_DECISION_REPLAY';
  q('COMMIT'); return {decision_id:P_DECISION,replay:true};
 }
 q(`INSERT INTO RI706_FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY(decision_id,artifact_id,model_version,batch_id,batch_version,input_release_id,input_bundle_sha256,target_release_id,target_bundle_sha256,evidence_reference,approved_by)
 SELECT ?,?,?,?,?,?,?,?,?,?,CURRENT_USER()`,[P_DECISION,P_ARTIFACT,modelVersion,batch,batchVersion,source,sourceBundle,P_TARGET_RELEASE,P_TARGET_BUNDLE,P_EVIDENCE]);
 q('COMMIT'); return {decision_id:P_DECISION,replay:false,lineage_partitions:partitionCount,lineage_rows:comparedRows};
} catch(e) {q('ROLLBACK');throw e;}
$$;
-- Human owner only. Ingestion and ML publishers cannot approve compatibility.
GRANT USAGE ON PROCEDURE RI706_FEATURE_STORE.SP_ADMIT_MODEL_RELEASE(VARCHAR,VARCHAR,VARCHAR,VARCHAR,VARCHAR)
 TO ROLE OH_LYME_DEV_OWNER;
CREATE OR REPLACE VIEW RI706_PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V AS
SELECT decision_id,artifact_id,model_version,batch_id,batch_version,input_release_id,input_bundle_sha256,
 target_release_id,target_bundle_sha256,evidence_reference,approved_by,approved_at
FROM RI706_FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY;
GRANT SELECT ON VIEW RI706_PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V TO ROLE OH_LYME_DEV_READ;

-- Explicit degraded-release authorization is separate from the candidate's
-- proposed inventory. Only a human owner can record this immutable decision.
CREATE TABLE IF NOT EXISTS RI706_FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS (
 decision_id VARCHAR NOT NULL,target_release_id VARCHAR NOT NULL,
 target_bundle_sha256 VARCHAR(64) NOT NULL,artifact_id VARCHAR NOT NULL,
 expected_rows NUMBER NOT NULL,reason VARCHAR NOT NULL,
 consumer_implications VARCHAR NOT NULL,rollback_plan VARCHAR NOT NULL,
 approved_by VARCHAR NOT NULL,approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE OR REPLACE PROCEDURE RI706_FEATURE_STORE.SP_APPROVE_RELEASE_COMPLETENESS_EXCEPTION(
 P_DECISION VARCHAR,P_RELEASE VARCHAR,P_BUNDLE VARCHAR,P_ARTIFACT VARCHAR,P_ROWS FLOAT,
 P_REASON VARCHAR,P_IMPLICATIONS VARCHAR,P_ROLLBACK VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if(!P_DECISION||!P_ARTIFACT||!Number.isInteger(P_ROWS)||P_ROWS<0||!P_REASON||P_REASON.length<20||!P_IMPLICATIONS||P_IMPLICATIONS.length<20||!P_ROLLBACK||P_ROLLBACK.length<20)throw 'INVALID_EXCEPTION';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1)throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_RELEASE,P_BUNDLE])!==1)throw 'EXCEPTION_REQUIRES_EXACT_RETAINED_RELEASE';
 var existing=q('SELECT target_release_id,target_bundle_sha256,artifact_id,expected_rows,reason,consumer_implications,rollback_plan FROM RI706_FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS WHERE decision_id=?',[P_DECISION]);
 var values=[P_RELEASE,P_BUNDLE,P_ARTIFACT,P_ROWS,P_REASON,P_IMPLICATIONS,P_ROLLBACK];
 if(existing.next()) {
  for(var i=0;i<values.length;i++)if(existing.getColumnValue(i+1)!==values[i])throw 'CHANGED_EXCEPTION_REPLAY';
  if(existing.next())throw 'DUPLICATE_EXCEPTION';q('COMMIT');return {replay:true};
 }
 q(`INSERT INTO RI706_FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS(decision_id,target_release_id,target_bundle_sha256,artifact_id,expected_rows,reason,consumer_implications,rollback_plan,approved_by) SELECT ?,?,?,?,?,?,?,?,CURRENT_USER()`,[P_DECISION].concat(values));
 q('COMMIT');return {decision_id:P_DECISION,replay:false};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE RI706_FEATURE_STORE.SP_APPROVE_RELEASE_COMPLETENESS_EXCEPTION(VARCHAR,VARCHAR,VARCHAR,VARCHAR,FLOAT,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_DEV_OWNER;
CREATE OR REPLACE VIEW RI706_PRESENTATION.RELEASE_COMPLETENESS_EXCEPTIONS_V AS
SELECT * FROM RI706_FEATURE_STORE.RELEASE_COMPLETENESS_EXCEPTIONS;
GRANT SELECT ON VIEW RI706_PRESENTATION.RELEASE_COMPLETENESS_EXCEPTIONS_V TO ROLE OH_LYME_DEV_READ;

-- Forward admission preserves existing immutable release manifests and makes
-- legacy rollback possible only with explicit completeness/degradation review.
CREATE TABLE IF NOT EXISTS RI706_FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS (
 release_id VARCHAR NOT NULL,bundle_sha256 VARCHAR(64) NOT NULL,
 manifest_json VARCHAR NOT NULL,manifest_sha256 VARCHAR(64) NOT NULL,
 evidence_reference VARCHAR NOT NULL,approved_by VARCHAR NOT NULL,
 approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE OR REPLACE PROCEDURE RI706_FEATURE_STORE.SP_ADMIT_RELEASE_COMPLETENESS(
 P_RELEASE VARCHAR,P_BUNDLE VARCHAR,P_MANIFEST VARCHAR,P_EVIDENCE VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if(!P_EVIDENCE||P_EVIDENCE.length<12||!P_MANIFEST||P_MANIFEST.length>100000)throw 'INVALID_ADMISSION';
var m=JSON.parse(P_MANIFEST);if(m.schema!=='atlas-release-completeness/v1'||!Array.isArray(m.artifacts)||!Array.isArray(m.views))throw 'INVALID_COMPLETENESS_MANIFEST';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK SET revision=revision+1 WHERE lock_key='MODEL_RELEASE'");
 if(one("SELECT COUNT(*) FROM RI706_FEATURE_STORE.MODEL_COMPATIBILITY_LOCK WHERE lock_key='MODEL_RELEASE'")!==1)throw 'AMBIGUOUS_LOCK';
 if(one(`SELECT COUNT(*) FROM RI706_PRESENTATION.SEMANTIC_RELEASES WHERE release_id=? AND bundle_sha256=? AND status IN ('CANDIDATE','PUBLISHED','RETIRED')`,[P_RELEASE,P_BUNDLE])!==1)throw 'WRONG_RELEASE';
 var existing=q('SELECT manifest_json,evidence_reference FROM RI706_FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS WHERE release_id=? AND bundle_sha256=?',[P_RELEASE,P_BUNDLE]);
 if(existing.next()) {
  if(existing.getColumnValue(1)!==P_MANIFEST||existing.getColumnValue(2)!==P_EVIDENCE||existing.next())throw 'CHANGED_COMPLETENESS_REPLAY';q('COMMIT');return {replay:true};
 }
 q(`INSERT INTO RI706_FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS(release_id,bundle_sha256,manifest_json,manifest_sha256,evidence_reference,approved_by) SELECT ?,?,?,LOWER(SHA2(?,256)),?,CURRENT_USER()`,[P_RELEASE,P_BUNDLE,P_MANIFEST,P_MANIFEST,P_EVIDENCE]);
 q('COMMIT');return {replay:false};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE RI706_FEATURE_STORE.SP_ADMIT_RELEASE_COMPLETENESS(VARCHAR,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_DEV_OWNER;
CREATE OR REPLACE VIEW RI706_PRESENTATION.RELEASE_COMPLETENESS_ADMISSIONS_V AS
SELECT * FROM RI706_FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS;
GRANT SELECT ON VIEW RI706_PRESENTATION.RELEASE_COMPLETENESS_ADMISSIONS_V TO ROLE OH_LYME_DEV_READ;
CREATE OR REPLACE VIEW RI706_PRESENTATION.CURRENT_RELEASE_COMPLETENESS_V AS
SELECT r.release_id,r.bundle_sha256,
 COALESCE(r.source_manifest:release_completeness,PARSE_JSON(a.manifest_json)) AS completeness
FROM RI706_PRESENTATION.CURRENT_RELEASE_V r_current
JOIN RI706_PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=r_current.release_id AND r.bundle_sha256=r_current.bundle_sha256
LEFT JOIN RI706_FEATURE_STORE.RELEASE_COMPLETENESS_ADMISSIONS a ON a.release_id=r.release_id AND a.bundle_sha256=r.bundle_sha256;
GRANT SELECT ON VIEW RI706_PRESENTATION.CURRENT_RELEASE_COMPLETENESS_V TO ROLE OH_LYME_DEV_READ;
