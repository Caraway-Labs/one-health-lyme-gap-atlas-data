-- DATA702: frozen ML138 batch. Installing DDL does not activate a batch.
USE DATABASE {{ DATABASE }};
CREATE TABLE IF NOT EXISTS FEATURE_STORE.SURVEILLANCE_SITUATION_PARTS (
 part_number NUMBER NOT NULL, part_text VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES (
 batch_id VARCHAR NOT NULL, batch_version VARCHAR NOT NULL, county_sha256 VARCHAR(64) NOT NULL,
 dictionary_sha256 VARCHAR(64) NOT NULL, manifest_json VARCHAR NOT NULL,
 dictionary_json VARCHAR NOT NULL, approval_json VARCHAR NOT NULL,
 state VARCHAR NOT NULL, created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
 activated_at TIMESTAMP_LTZ,published_by VARCHAR NOT NULL DEFAULT CURRENT_USER()
);
CREATE TABLE IF NOT EXISTS FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS (
 batch_id VARCHAR NOT NULL,batch_version VARCHAR NOT NULL,model_id VARCHAR NOT NULL,
 model_version VARCHAR NOT NULL,county_fips VARCHAR(5) NOT NULL,state_code VARCHAR(2) NOT NULL,
 population NUMBER NOT NULL,class_id VARCHAR NOT NULL,probabilities VARIANT NOT NULL
);
CREATE TABLE IF NOT EXISTS FEATURE_STORE.SURVEILLANCE_SITUATION_CLASSES (
 batch_id VARCHAR NOT NULL,batch_version VARCHAR NOT NULL,model_id VARCHAR NOT NULL,
 class_id VARCHAR NOT NULL,class_metadata VARIANT NOT NULL
);
CREATE TABLE IF NOT EXISTS FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER (
 pointer_key VARCHAR NOT NULL,batch_id VARCHAR,batch_version VARCHAR,revision NUMBER NOT NULL
);
INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER
 SELECT 'CURRENT',NULL,NULL,0 WHERE NOT EXISTS (
 SELECT 1 FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT');

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(P_NUMBER FLOAT,P_TEXT VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
if(!Number.isInteger(P_NUMBER)||P_NUMBER<0||P_NUMBER>30||typeof P_TEXT!=='string'||P_TEXT.length<1||P_TEXT.length>200000) throw 'INVALID_PART';
try {
 q('BEGIN TRANSACTION');
 var lock=q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET revision=revision+1 WHERE pointer_key='CURRENT'");
 var count=q("SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT'");count.next();if(count.getColumnValue(1)!==1)throw 'AMBIGUOUS_POINTER';
 var part=q('SELECT part_text FROM FEATURE_STORE.SURVEILLANCE_SITUATION_PARTS WHERE part_number=?',[P_NUMBER]);
 if(part.next()) {if(part.getColumnValue(1)!==P_TEXT||part.next())throw 'CHANGED_PART_REPLAY';}
 else {
  var approved=q('SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES');approved.next();if(approved.getColumnValue(1)!==0)throw 'BATCH_ALREADY_IMMUTABLE';
  q('INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_PARTS VALUES (?,?)',[P_NUMBER,P_TEXT]);
 }
 q('COMMIT');return {part_number:P_NUMBER};
}catch(e){q('ROLLBACK');throw e;}
$$;

CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_PUBLISH_SURVEILLANCE_SITUATIONS(P_MANIFEST VARCHAR,P_DICTIONARY VARCHAR,P_APPROVAL VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
var release='governed-2026-10-15-january-climate-prod';
var bundle='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d';
var countyDigest='02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b';
var dictionaryDigest='c0fecc0766c7e485b670624793cd2b02a1c8bafd49c740bcc8db9c62e9d2494b';
if(typeof P_MANIFEST!=='string'||P_MANIFEST.length>20000||typeof P_DICTIONARY!=='string'||P_DICTIONARY.length>20000||typeof P_APPROVAL!=='string'||P_APPROVAL.length>10000)throw 'INVALID_DOCUMENT';
var m=JSON.parse(P_MANIFEST),d=JSON.parse(P_DICTIONARY),a=JSON.parse(P_APPROVAL);
for(var i=0;i<2;i++) {
 var x=i===0?m:a;
 if(x.batch_id!=='surveillance-situation-batch'||x.batch_version!=='v1'||x.approval_state!=='approved_for_data_handoff'||x.release_id!==release||x.bundle_sha256!==bundle||x.county_sha256!==countyDigest||x.class_dictionary_sha256!==dictionaryDigest||x.git_sha!=='cd936fe345664e606c916b137dd642caa0d6d73b'||x.result_commit!=='a2f9bad41f1ddb793e364399afbdd5fbad008b7a')throw 'WRONG_APPROVED_LINEAGE';
}
if(a.approver!=='Matthew Caraway'||a.approved_at!=='2026-10-18T11:37:14-06:00')throw 'WRONG_HANDOFF_APPROVAL';
try {
 q('BEGIN TRANSACTION');
 if(one('SELECT LOWER(SHA2(?,256))',[P_MANIFEST])!=='853c2ad3db1de297f73138cb688bb9a7372e30d0af55720fac2429b8955b4b99'||
    one('SELECT LOWER(SHA2(?,256))',[P_APPROVAL])!=='8fa1f3292a0943c5a8512b7d59a93bb18bc87d47bd2483ff4d8ee71bfbb62b86')throw 'HANDOFF_DOCUMENT_DRIFT';
 q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET revision=revision+1 WHERE pointer_key='CURRENT'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT'")!==1)throw 'AMBIGUOUS_POINTER';
 if(one(`SELECT COUNT(*) FROM PRESENTATION.CURRENT_RELEASE_V WHERE release_id=? AND bundle_sha256=?`,[release,bundle])!==1)throw 'INCOMPATIBLE_CURRENT_RELEASE';
 if(one('SELECT LOWER(SHA2(?,256))',[P_DICTIONARY])!==dictionaryDigest)throw 'DICTIONARY_DIGEST_MISMATCH';
 var bytes=one("SELECT LISTAGG(part_text,'') WITHIN GROUP (ORDER BY part_number) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_PARTS");
 if(one('SELECT LOWER(SHA2(?,256))',[bytes])!==countyDigest)throw 'COUNTY_DIGEST_MISMATCH';
 var existing=q('SELECT county_sha256,dictionary_sha256,manifest_json,dictionary_json,approval_json FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES');
 if(existing.next()) {
  if(existing.getColumnValue(1)!==countyDigest||existing.getColumnValue(2)!==dictionaryDigest||existing.getColumnValue(3)!==P_MANIFEST||existing.getColumnValue(4)!==P_DICTIONARY||existing.getColumnValue(5)!==P_APPROVAL||existing.next())throw 'CHANGED_BATCH_REPLAY';
  q('COMMIT');return {batch_id:m.batch_id,batch_version:'v1',replay:true};
 }
 var doc=JSON.parse(bytes),known={},models=['surveillance-situation-four-state','surveillance-situation-tick-pathogen'];
 if(doc.models.length!==2)throw 'WRONG_MODEL_COUNT';
 for(var modelIndex=0;modelIndex<2;modelIndex++) {
  var model=doc.models[modelIndex],id=model.model_id;
  if(models.indexOf(id)<0||known[id]||model.model_version!=='v1'||model.rows.length!==3144)throw 'WRONG_MODEL';
  known[id]=true;var fips={},counts=[0,0,0,0],unknown=0;
  for(var n=0;n<model.rows.length;n++) {
   var r=model.rows[n];if(!/^[0-9]{5}$/.test(r.county_fips)||fips[r.county_fips]||r.probabilities.length!==4)throw 'INVALID_COUNTY';fips[r.county_fips]=true;
   var sum=0;for(var p=0;p<4;p++) {var v=r.probabilities[p];if(v.class_id!==id+'.v1.class-'+p||typeof v.probability!=='number'||!isFinite(v.probability)||v.probability<0||v.probability>1)throw 'INVALID_PROBABILITY';sum+=v.probability;}
   if(Math.abs(sum-1)>1e-6)throw 'INVALID_PROBABILITY_SUM';
   var cls=Number(r.class_id.slice(-1));if(r.class_id!==id+'.v1.class-'+cls||cls<0||cls>3)throw 'INVALID_CLASS';counts[cls]++;
   var isUnknown=cls===(id===models[0]?1:3),akHi=/^(02|15)/.test(r.county_fips);
   if(isUnknown!==akHi)throw 'UNKNOWN_SCOPE_MISMATCH';if(isUnknown)unknown++;
  }
  var expected=id===models[0]?[801,35,112,2196]:[1325,1687,97,35];if(JSON.stringify(counts)!==JSON.stringify(expected)||unknown!==35)throw 'CLASS_COUNT_DRIFT';
 }
 q(`INSERT INTO FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS
 SELECT 'surveillance-situation-batch','v1',m.value:model_id::VARCHAR,m.value:model_version::VARCHAR,
 r.value:county_fips::VARCHAR,r.value:state::VARCHAR,r.value:population::NUMBER,r.value:class_id::VARCHAR,r.value:probabilities
 FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(?):models)) m,LATERAL FLATTEN(INPUT=>m.value:rows) r`,[bytes]);
 if(one(`SELECT COUNT(*) FROM FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS a LEFT JOIN PRESENTATION.CURRENT_COUNTY_ATLAS_V c ON a.county_fips=c.fips WHERE c.fips IS NULL`)!==0)throw 'GEOGRAPHY_MISMATCH';
 q(`INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_CLASSES SELECT 'surveillance-situation-batch','v1',m.value:id::VARCHAR,c.value:id::VARCHAR,c.value
 FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(?):models)) m,LATERAL FLATTEN(INPUT=>m.value:classes)c`,[P_DICTIONARY]);
 q(`INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES(batch_id,batch_version,county_sha256,dictionary_sha256,manifest_json,dictionary_json,approval_json,state,activated_at)
 VALUES ('surveillance-situation-batch','v1',?,?,?,?,?,'APPROVED',CURRENT_TIMESTAMP())`,[countyDigest,dictionaryDigest,P_MANIFEST,P_DICTIONARY,P_APPROVAL]);
 q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET batch_id='surveillance-situation-batch',batch_version='v1' WHERE pointer_key='CURRENT'");
 q("INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_EVENTS(action,reason,actor) SELECT 'PUBLISH',?,CURRENT_USER()",['ML138 approved v1 county SHA256 '+countyDigest]);
 q('COMMIT');return {batch_id:m.batch_id,batch_version:'v1',replay:false};
}catch(e){q('ROLLBACK');throw e;}
$$;

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V AS
SELECT a.county_fips,a.model_id,a.model_version,a.class_id,a.probabilities,a.state_code,a.population,
 c.class_metadata:name::VARCHAR AS class_name,c.class_metadata:description::VARCHAR AS class_description,
 c.class_metadata:must_not_be_read_as AS limitations,b.batch_id,b.batch_version,b.county_sha256,
 b.dictionary_sha256,r.release_id,r.bundle_sha256,
 PARSE_JSON(b.manifest_json):release_id::VARCHAR AS input_release_id,
 PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR AS input_bundle_sha256,
 PARSE_JSON(b.manifest_json):git_sha::VARCHAR AS fit_git_sha,
 PARSE_JSON(b.manifest_json):feature_contract AS feature_contract,
 PARSE_JSON(b.approval_json) AS handoff_approval,b.activated_at,
 provenance.sources AS source_provenance,
 PARSE_JSON(b.manifest_json) AS model_provenance
FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER p
JOIN FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b ON b.batch_id=p.batch_id AND b.batch_version=p.batch_version AND b.state='APPROVED'
JOIN FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS a ON a.batch_id=b.batch_id AND a.batch_version=b.batch_version
JOIN FEATURE_STORE.SURVEILLANCE_SITUATION_CLASSES c ON c.batch_id=a.batch_id AND c.batch_version=a.batch_version AND c.model_id=a.model_id AND c.class_id=a.class_id
JOIN (SELECT release_id,OBJECT_AGG(source_key,OBJECT_CONSTRUCT(
 'source_id',source_id,'dataset_id',dataset_id,'vintage',vintage,
 'source_url',source_url,'limitations',note)) AS sources
 FROM PRESENTATION.SEMANTIC_DATA_SOURCES GROUP BY release_id) provenance
 ON provenance.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
JOIN PRESENTATION.CURRENT_RELEASE_V r ON (
 (r.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR AND r.bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR)
 OR EXISTS (SELECT 1 FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY admission
 WHERE admission.artifact_id=a.model_id AND admission.batch_id=b.batch_id
 AND admission.input_release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
 AND admission.input_bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR
 AND admission.target_release_id=r.release_id AND admission.target_bundle_sha256=r.bundle_sha256))
WHERE p.pointer_key='CURRENT';
GRANT SELECT ON VIEW PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V TO ROLE OH_LYME_{{ ENV }}_READ;
CREATE OR REPLACE VIEW PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V AS
SELECT c.fips AS county_fips,m.model_id,r.release_id,r.bundle_sha256,
 IFF(s.class_id IS NOT NULL,'AVAILABLE','UNAVAILABLE') AS availability,
 CASE WHEN s.class_id IS NOT NULL THEN NULL
 WHEN p.batch_id IS NULL THEN IFF(EXISTS(
  SELECT 1 FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES WHERE state='APPROVED'),
  'DEACTIVATED','NOT_PUBLISHED')
 WHEN b.batch_id IS NULL OR b.state<>'APPROVED' THEN 'UNAPPROVED_BATCH'
 WHEN NOT (r.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR AND
           r.bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR)
 AND NOT EXISTS(SELECT 1 FROM FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY admission
  WHERE admission.artifact_id=m.model_id AND admission.batch_id=b.batch_id
  AND admission.input_release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR
  AND admission.input_bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR
  AND admission.target_release_id=r.release_id AND admission.target_bundle_sha256=r.bundle_sha256)
 THEN 'INCOMPATIBLE_RELEASE' ELSE 'MISSING_ASSIGNMENT' END AS unavailable_reason,
 b.batch_id,b.batch_version,PARSE_JSON(b.manifest_json):release_id::VARCHAR AS input_release_id,
 s.class_id
FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V c
CROSS JOIN (SELECT column1 AS model_id FROM VALUES
 ('surveillance-situation-four-state'),('surveillance-situation-tick-pathogen'))m
CROSS JOIN PRESENTATION.CURRENT_RELEASE_V r
LEFT JOIN FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER p ON p.pointer_key='CURRENT'
LEFT JOIN FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b ON b.batch_id=p.batch_id AND b.batch_version=p.batch_version
LEFT JOIN PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V s ON s.county_fips=c.fips AND s.model_id=m.model_id;
GRANT SELECT ON VIEW PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V TO ROLE OH_LYME_{{ ENV }}_READ;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_STAGE_SURVEILLANCE_SITUATION_PART(FLOAT,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_ML_PUBLISHER;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_PUBLISH_SURVEILLANCE_SITUATIONS(VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_ML_PUBLISHER;

CREATE TABLE IF NOT EXISTS FEATURE_STORE.SURVEILLANCE_SITUATION_EVENTS (
 action VARCHAR NOT NULL,reason VARCHAR NOT NULL,actor VARCHAR NOT NULL,
 recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE OR REPLACE PROCEDURE FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(P_ACTIVE BOOLEAN,P_REASON VARCHAR)
RETURNS VARIANT LANGUAGE JAVASCRIPT EXECUTE AS OWNER AS
$$
function q(s,b){return snowflake.createStatement({sqlText:s,binds:b||[]}).execute();}
function one(s,b){var r=q(s,b);if(!r.next())throw 'MISSING_EVIDENCE';return r.getColumnValue(1);}
if(typeof P_ACTIVE!=='boolean'||!P_REASON||P_REASON.length<12)throw 'INVALID_ROLLBACK_REQUEST';
try {
 q('BEGIN TRANSACTION');
 q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET revision=revision+1 WHERE pointer_key='CURRENT'");
 if(one("SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER WHERE pointer_key='CURRENT'")!==1)throw 'AMBIGUOUS_POINTER';
 if(P_ACTIVE) {
  if(one(`SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b JOIN PRESENTATION.CURRENT_RELEASE_V r ON r.release_id=PARSE_JSON(b.manifest_json):release_id::VARCHAR AND r.bundle_sha256=PARSE_JSON(b.manifest_json):bundle_sha256::VARCHAR WHERE b.batch_id='surveillance-situation-batch' AND b.batch_version='v1' AND b.state='APPROVED'`)!==1)throw 'NO_COMPATIBLE_APPROVED_BATCH';
  q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET batch_id='surveillance-situation-batch',batch_version='v1' WHERE pointer_key='CURRENT'");
 }else q("UPDATE FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER SET batch_id=NULL,batch_version=NULL WHERE pointer_key='CURRENT'");
 q('INSERT INTO FEATURE_STORE.SURVEILLANCE_SITUATION_EVENTS(action,reason,actor) SELECT ?,?,CURRENT_USER()',[P_ACTIVE?'ACTIVATE':'DEACTIVATE',P_REASON]);
 q('COMMIT');return {active:P_ACTIVE};
}catch(e){q('ROLLBACK');throw e;}
$$;
GRANT USAGE ON PROCEDURE FEATURE_STORE.SP_SET_SURVEILLANCE_SITUATION_ACTIVE(BOOLEAN,VARCHAR) TO ROLE OH_LYME_{{ ENV }}_OWNER;
