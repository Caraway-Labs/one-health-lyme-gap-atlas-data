-- Forward correction: Snowflake SQL BOOLEAN maps to JavaScript number 0/1.
-- Preserve V158 and all immutable model/release provenance. No activation occurs.
USE DATABASE {{ DATABASE }};
CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(P_ACTIVE BOOLEAN,P_REASON VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if((P_ACTIVE!==0&&P_ACTIVE!==1)||typeof P_REASON!=='string'||P_REASON.length<12)throw 'INVALID_ROLLBACK_REQUEST';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET revision=revision+1 WHERE pointer_key='CURRENT'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT'")!==1)throw 'AMBIGUOUS_POINTER';
 if(P_ACTIVE===1) {
  if(one(`SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b
   JOIN FEATURE_STORE.SURVEILLANCE_SITUATION_AUTHORIZATIONS a ON a.decision_id=b.data_authorization_id AND a.county_sha256=b.county_sha256
   CROSS JOIN PRESENTATION.CURRENT_RELEASE_V r
   LEFT JOIN (SELECT batch_id,batch_version,input_release_id,input_bundle_sha256,
    target_release_id,target_bundle_sha256,COUNT(DISTINCT artifact_id) AS admitted_models
    FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY
    WHERE artifact_id IN ('surveillance-situation-four-state','surveillance-situation-tick-pathogen')
    AND model_version='v1'
    GROUP BY batch_id,batch_version,input_release_id,input_bundle_sha256,target_release_id,target_bundle_sha256) admission
    ON admission.batch_id=b.batch_id AND admission.batch_version=b.batch_version
    AND admission.input_release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
    AND admission.input_bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR
    AND admission.target_release_id=r.release_id AND admission.target_bundle_sha256=r.bundle_sha256
   WHERE b.batch_id='surveillance-situation-batch' AND b.batch_version='v1' AND b.state='APPROVED'
   AND a.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
   AND a.bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR
   AND ((r.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
    AND r.bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR)
    OR admission.admitted_models=2)`)!==1)throw 'NO_COMPATIBLE_APPROVED_BATCH';
  q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET batch_id='surveillance-situation-batch',batch_version='v1' WHERE pointer_key='CURRENT'");
 }else q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET batch_id=NULL,batch_version=NULL WHERE pointer_key='CURRENT'");
 q('INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_EVENTS(action,reason,actor) SELECT ?,?,CURRENT_USER()',[P_ACTIVE===1?'ACTIVATE':'DEACTIVATE',P_REASON]);
 q('COMMIT');return {active:P_ACTIVE===1};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(BOOLEAN,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_OWNER;
