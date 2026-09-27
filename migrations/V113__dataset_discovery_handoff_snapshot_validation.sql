-- Data #450 forward hardening; draft until ADR 0041 and protected migration review.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION(
  P_RECOMMENDATION_VERSION_ID VARCHAR, P_REVIEW_EVENT_ID VARCHAR)
RETURNS VARIANT
LANGUAGE JAVASCRIPT
EXECUTE AS OWNER
AS
$$
function required(value, maximum, label) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum) {
    throw new Error('INVALID_' + label);
  }
  return value;
}
function query(sql, binds) {
  return snowflake.createStatement({sqlText: sql, binds: binds}).execute();
}
function hash(value) {
  var rows = query('SELECT LOWER(SHA2(?, 256))', [value]);
  if (!rows.next()) throw new Error('HASH_UNAVAILABLE');
  return rows.getColumnValue(1);
}
required(P_RECOMMENDATION_VERSION_ID, 64, 'VERSION_ID');
required(P_REVIEW_EVENT_ID, 64, 'REVIEW_EVENT_ID');
var caller = query(
  "SELECT SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME'), " +
  "SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_TYPE'), " +
  "SYS_CONTEXT('SNOWFLAKE$SESSION', 'ROLE')", []);
if (!caller.next()) throw new Error('CALLER_UNAVAILABLE');
var user = caller.getColumnValue(1);
var type = caller.getColumnValue(2);
var role = caller.getColumnValue(3);
if (caller.next() || type !== 'USER_PERSON' ||
    typeof user !== 'string' || user.length < 1 || user.length > 200 ||
    role !== 'OH_LYME_{{ ENV }}_DATASET_DISCOVERY_REVIEWER') {
  throw new Error('UNAUTHORIZED_HANDOFF_CALLER');
}
var operation_key = 'handoff-v1:' + P_RECOMMENDATION_VERSION_ID;
var handoff_id = hash(operation_key);

snowflake.execute({sqlText: 'BEGIN TRANSACTION'});
try {
  var lock = snowflake.createStatement({
    sqlText: "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION " +
             "SET revision = revision + 1, touched_at = CURRENT_TIMESTAMP() " +
             "WHERE lock_name = 'V1_WRITES'"
  });
  lock.execute();
  if (lock.getNumRowsAffected() !== 1) throw new Error('SERIALIZATION_ROW_MISSING');
  var allowed = query(
    'SELECT reviewer_user FROM DATASET_DISCOVERY.REVIEWER_ALLOWLIST ' +
    'WHERE reviewer_user = ? AND is_active = TRUE', [user]);
  if (!allowed.next() || allowed.next()) throw new Error('REVIEWER_NOT_ALLOWLISTED');

  var old = query(
    'SELECT handoff_id, review_event_id, relationship_type, disposition, ' +
    'investigation_status, acquisition_boundary ' +
    'FROM GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS ' +
    'WHERE operation_key = ?', [operation_key]);
  if (old.next()) {
    var old_id = old.getColumnValue(1);
    var old_event = old.getColumnValue(2);
    var old_relationship = old.getColumnValue(3);
    var old_disposition = old.getColumnValue(4);
    var old_status = old.getColumnValue(5);
    var old_boundary = old.getColumnValue(6);
    if (old.next() || old_id !== handoff_id ||
        old_event !== P_REVIEW_EVENT_ID) throw new Error('CONFLICTING_HANDOFF_REPLAY');
    snowflake.execute({sqlText: 'COMMIT'});
    return {handoff_id: handoff_id, operation_key: operation_key,
      recommendation_version_id: P_RECOMMENDATION_VERSION_ID,
      review_event_id: P_REVIEW_EVENT_ID, relationship_type: old_relationship,
      disposition: old_disposition,
      investigation_status: old_status, acquisition_boundary: old_boundary};
  }

  var accepted = query(
    'SELECT rec.recommendation_id, rec.run_id, rec.resource_key, ' +
    'rec.catalog_dataset_id, rec.catalog_resource_id, rec.evidence_snapshot_id, ' +
    'rec.relationship_type, rec.rights_state, rev.reviewer_user ' +
    'FROM DATASET_DISCOVERY.RECOMMENDATIONS rec ' +
    'JOIN DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE state ' +
    'ON state.recommendation_version_id = rec.recommendation_version_id ' +
    'JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev ' +
    'ON rev.review_event_id = state.latest_review_event_id ' +
    'WHERE rec.recommendation_version_id = ? AND rec.commit_complete = TRUE ' +
    "AND state.review_state = 'ACCEPTED_FOR_INVESTIGATION' " +
    'AND rev.review_event_id = ? AND rev.reviewer_user = ?',
    [P_RECOMMENDATION_VERSION_ID, P_REVIEW_EVENT_ID, user]);
  if (!accepted.next()) throw new Error('REJECTED_OR_STALE_HANDOFF');
  var rec_id = accepted.getColumnValue(1);
  var run_id = accepted.getColumnValue(2);
  var resource_key = accepted.getColumnValue(3);
  var dataset_id = accepted.getColumnValue(4);
  var resource_id = accepted.getColumnValue(5);
  var snapshot_id = accepted.getColumnValue(6);
  var relationship = accepted.getColumnValue(7);
  var rights = accepted.getColumnValue(8);
  if (accepted.next()) throw new Error('DUPLICATE_RECOMMENDATION_STATE');

  var catalog = query(
    'SELECT r.resource_type FROM GOVERNANCE.CATALOG_RESOURCES r ' +
    'JOIN GOVERNANCE.CATALOG_DATASETS d ' +
    'ON d.catalog_dataset_id = r.catalog_dataset_id ' +
    'WHERE r.resource_key = ? AND r.catalog_resource_id = ? ' +
    'AND d.catalog_dataset_id = ? AND r.is_active = TRUE AND d.is_current = TRUE',
    [resource_key, resource_id, dataset_id]);
  if (!catalog.next()) throw new Error('STALE_CATALOG_IDENTITY');
  var resource_type = catalog.getColumnValue(1);
  if (catalog.next()) throw new Error('AMBIGUOUS_CATALOG_IDENTITY');
  var evidence = query(
    'SELECT DISTINCT observation_id FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE ' +
    'WHERE recommendation_version_id = ? AND catalog_dataset_id = ? ' +
    'AND catalog_resource_id = ? ORDER BY observation_id LIMIT 101',
    [P_RECOMMENDATION_VERSION_ID, dataset_id, resource_id]);
  var evidence_ids = [];
  while (evidence.next()) evidence_ids.push(evidence.getColumnValue(1));
  if (evidence_ids.length < 1 || evidence_ids.length > 100) {
    throw new Error('MISSING_EVIDENCE');
  }
  var all_evidence = query(
    'SELECT COUNT(DISTINCT observation_id) ' +
    'FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE ' +
    'WHERE recommendation_version_id = ?', [P_RECOMMENDATION_VERSION_ID]);
  if (!all_evidence.next() || all_evidence.getColumnValue(1) !== evidence_ids.length) {
    throw new Error('AMBIGUOUS_EVIDENCE');
  }
  var observation = query(
    'SELECT COUNT(DISTINCT o.observation_id) ' +
    'FROM GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o ' +
    'JOIN DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE e ' +
    'ON e.observation_id = o.observation_id ' +
    'WHERE e.recommendation_version_id = ? AND o.catalog_dataset_id = ? ' +
    'AND o.catalog_resource_id = ? AND o.canonical_resource_key = ? ' +
    'AND o.ingestion_run_id = ?',
    [P_RECOMMENDATION_VERSION_ID, dataset_id, resource_id,
     resource_key, snapshot_id]);
  if (!observation.next() || observation.getColumnValue(1) !== evidence_ids.length) {
    throw new Error('EVIDENCE_CATALOG_MISMATCH');
  }
  var finding = query(
    'SELECT rights_state FROM GOVERNANCE.RESOURCE_RIGHTS_FINDINGS ' +
    'WHERE resource_key = ? AND reviewed_by IS NOT NULL ' +
    'AND LENGTH(TRIM(reviewed_by)) > 0 ' +
    'AND evidence_reference IS NOT NULL ' +
    'AND LENGTH(TRIM(evidence_reference)) > 0 ' +
    'ORDER BY reviewed_at DESC, finding_id DESC LIMIT 1', [resource_key]);
  var reviewed_rights = finding.next() ? finding.getColumnValue(1) : null;
  var status = query(
    'SELECT already_governed FROM DATASET_DISCOVERY.V_CANDIDATE_GOVERNED_STATUS ' +
    'WHERE resource_key = ?', [resource_key]);
  var governed = status.next() && status.getColumnValue(1) === true;
  var disposition = reviewed_rights === 'KNOWN_PROHIBITED' ? 'POLICY_BLOCKED' :
    governed ? 'ALREADY_GOVERNED' : 'HANDED_OFF';
  var boundary = reviewed_rights === 'KNOWN_RESTRICTED' ||
    reviewed_rights === 'KNOWN_PROHIBITED' ||
    resource_type === 'CONTROLLED_ACCESS' ? 'NO_AUTOMATED_ACQUISITION' :
    'INVESTIGATE_BEFORE_ACQUISITION';
  var investigation_status = disposition === 'HANDED_OFF' ? 'PENDING' :
    disposition;
  query(
    'INSERT INTO GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS (' +
    'handoff_id, operation_key, recommendation_id, recommendation_version_id, ' +
    'run_id, review_event_id, reviewer_user, resource_key, catalog_dataset_id, ' +
    'catalog_resource_id, evidence_snapshot_id, evidence_observation_ids, ' +
    'relationship_type, rights_assertion, reviewed_rights_state, ' +
    'acquisition_boundary, disposition, investigation_status) ' +
    'SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?), ?, ?, ?, ?, ?, ?',
    [handoff_id, operation_key, rec_id, P_RECOMMENDATION_VERSION_ID,
     run_id, P_REVIEW_EVENT_ID, user, resource_key, dataset_id, resource_id,
     snapshot_id, JSON.stringify(evidence_ids), relationship, rights,
     reviewed_rights, boundary, disposition, investigation_status]);
  snowflake.execute({sqlText: 'COMMIT'});
  return {handoff_id: handoff_id, operation_key: operation_key,
    recommendation_version_id: P_RECOMMENDATION_VERSION_ID,
    review_event_id: P_REVIEW_EVENT_ID, relationship_type: relationship,
    disposition: disposition,
    investigation_status: investigation_status, acquisition_boundary: boundary};
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;
