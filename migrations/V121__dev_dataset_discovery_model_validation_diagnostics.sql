-- DEV-only forward extension of the bounded candidate decision audit. V120 remains immutable.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME(
  P_REQUEST_JSON VARCHAR
)
COPY GRANTS
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
required(P_REQUEST_JSON, 16384, 'REQUEST');
var r = JSON.parse(P_REQUEST_JSON);
if (r === null || typeof r !== 'object' || Array.isArray(r)) {
  throw new Error('INVALID_REQUEST_OBJECT');
}
var allowed = {
  operation_key: true, run_id: true, resource_key: true,
  catalog_dataset_id: true, catalog_resource_id: true,
  evidence_snapshot_id: true, outcome: true, reason_code: true,
  decision_record: true
};
for (var key in r) {
  if (Object.prototype.hasOwnProperty.call(r, key) &&
      !Object.prototype.hasOwnProperty.call(allowed, key)) {
    throw new Error('UNEXPECTED_REQUEST_FIELD');
  }
}
required(r.operation_key, 200, 'OPERATION_KEY');
required(r.run_id, 200, 'RUN_ID');
required(r.resource_key, 500, 'RESOURCE_KEY');
required(r.catalog_dataset_id, 200, 'CATALOG_DATASET_ID');
required(r.catalog_resource_id, 200, 'CATALOG_RESOURCE_ID');
required(r.evidence_snapshot_id, 200, 'SNAPSHOT_ID');
if (!/^[A-Z][A-Z0-9_]{0,79}$/.test(required(r.outcome, 80, 'OUTCOME'))) {
  throw new Error('INVALID_OUTCOME');
}
if (r.decision_record === undefined) r.decision_record = null;
if (r.decision_record !== null) {
  if (typeof r.decision_record !== 'object' || Array.isArray(r.decision_record) ||
      JSON.stringify(r.decision_record).length > 10000) {
    throw new Error('INVALID_DECISION_RECORD');
  }
  var safe = {
    model_id: true, provider: true, model_fingerprint: true, config_fingerprint: true,
    prompt_version: true, task_type: true,
    model_call_attempted: true, model_call_succeeded_transport: true,
    structured_parse_succeeded: true, validation_stage: true,
    validation_error_code: true, validation_field: true,
    validator_name: true, validator_version: true, token_usage: true,
    response_schema_version: true, response_fingerprint: true,
    classification: true, relationship: true, relationship_basis: true, relevance: true,
    dimensions: true, cited_evidence_ids: true, unknown_fields: true,
    validator_result: true, normalized_reason: true, final_outcome: true
  };
  for (var field in r.decision_record) {
    if (!Object.prototype.hasOwnProperty.call(safe, field)) {
      throw new Error('UNEXPECTED_DECISION_FIELD');
    }
  }
  if (r.decision_record.final_outcome !== r.outcome) {
    throw new Error('DECISION_OUTCOME_MISMATCH');
  }
  var d = r.decision_record;
  if (!/^[0-9a-f]{64}$/.test(required(d.config_fingerprint, 64, 'CONFIG_FINGERPRINT')) ||
      ['RELATIONSHIP', 'CLASSIFICATION', 'RATIONALE', 'PROPOSALS',
       'NOT_CALLED'].indexOf(d.task_type) < 0 ||
      !/^[A-Z][A-Z0-9_]{0,79}$/.test(required(d.normalized_reason, 80, 'NORMALIZED_REASON')) ||
      d.normalized_reason !== r.reason_code ||
      !/^[A-Z][A-Z0-9_]{0,79}$/.test(required(d.validator_result, 80, 'VALIDATOR_RESULT')) ||
      (d.relevance !== null && d.relevance !== 0 && d.relevance !== 1 && d.relevance !== 2)) {
    throw new Error('INVALID_DECISION_SHAPE');
  }
  var scalars = ['model_id', 'model_fingerprint', 'prompt_version',
                 'classification', 'relationship', 'relationship_basis',
                 'provider', 'validation_stage', 'validation_error_code',
                 'validation_field', 'validator_name', 'validator_version',
                 'response_schema_version'];
  for (var i = 0; i < scalars.length; i++) {
    var scalar = scalars[i];
    if (d[scalar] !== null && d[scalar] !== undefined &&
        (typeof d[scalar] !== 'string' || d[scalar].length > 120 ||
         !/^[A-Za-z0-9_.:-]+$/.test(d[scalar]))) {
      throw new Error('INVALID_DECISION_SCALAR');
    }
  }
  var booleans = ['model_call_attempted', 'model_call_succeeded_transport',
                  'structured_parse_succeeded'];
  for (var b = 0; b < booleans.length; b++) {
    if (d[booleans[b]] !== undefined && typeof d[booleans[b]] !== 'boolean') {
      throw new Error('INVALID_DECISION_BOOLEAN');
    }
  }
  if (d.task_type === 'NOT_CALLED' && d.model_call_attempted === true ||
      d.model_call_succeeded_transport === true && d.model_call_attempted !== true ||
      d.structured_parse_succeeded === true && d.model_call_succeeded_transport !== true) {
    throw new Error('INVALID_MODEL_CALL_SEQUENCE');
  }
  if (d.response_fingerprint !== undefined && d.response_fingerprint !== null &&
      !/^[0-9a-f]{64}$/.test(d.response_fingerprint)) {
    throw new Error('INVALID_RESPONSE_FINGERPRINT');
  }
  if (d.token_usage !== undefined && d.token_usage !== null) {
    var usage_names = ['input_tokens', 'output_tokens', 'cached_input_tokens',
                       'reasoning_tokens', 'estimated_spend_cents'];
    if (typeof d.token_usage !== 'object' || Array.isArray(d.token_usage) ||
        Object.keys(d.token_usage).length !== usage_names.length ||
        usage_names.some(function(name) {
          return typeof d.token_usage[name] !== 'number' ||
                 !isFinite(d.token_usage[name]) ||
                 Math.floor(d.token_usage[name]) !== d.token_usage[name] ||
                 d.token_usage[name] < 0 || d.token_usage[name] > 1000000000;
        })) {
      throw new Error('INVALID_DECISION_TOKEN_USAGE');
    }
  }
  var names = ['relevance', 'geography', 'variables', 'time', 'provenance',
               'freshness', 'rights_clarity', 'complementarity'];
  if (d.dimensions === null || typeof d.dimensions !== 'object' ||
      Array.isArray(d.dimensions) ||
      Object.keys(d.dimensions).some(function(name) { return names.indexOf(name) < 0; })) {
    throw new Error('INVALID_DECISION_DIMENSIONS');
  }
  var dimension_names = Object.keys(d.dimensions);
  var lists = [d.cited_evidence_ids, d.unknown_fields];
  for (var j = 0; j < dimension_names.length; j++) {
    var name = dimension_names[j];
    var dimension = d.dimensions[name];
    if (dimension === null || typeof dimension !== 'object' ||
        Object.keys(dimension).some(function(key) {
          return ['value', 'cited_evidence_ids'].indexOf(key) < 0;
        }) ||
        [null, 0, 1, 2].indexOf(dimension.value) < 0 ||
        !Array.isArray(dimension.cited_evidence_ids)) {
      throw new Error('INVALID_DECISION_DIMENSION');
    }
    lists.push(dimension.cited_evidence_ids);
  }
  for (var k = 0; k < lists.length; k++) {
    var list = lists[k];
    if (!Array.isArray(list) || list.length > 25 || list.some(function(item) {
        return typeof item !== 'string' || item.length < 1 || item.length > 200 ||
          !/^[A-Za-z0-9_.:-]+$/.test(item);
    })) {
      throw new Error('INVALID_DECISION_LIST');
    }
  }
}
if (r.reason_code === undefined) r.reason_code = null;
if (r.reason_code !== null &&
    !/^[A-Z][A-Z0-9_]{0,79}$/.test(required(r.reason_code, 80, 'REASON_CODE'))) {
  throw new Error('INVALID_REASON_CODE');
}

var decision_hash = null;
if (r.decision_record !== null) {
  var hash_result = query('SELECT SHA2(TO_JSON(PARSE_JSON(?)), 256)',
                          [JSON.stringify(r.decision_record)]);
  hash_result.next();
  decision_hash = hash_result.getColumnValue(1);
}
snowflake.execute({sqlText: 'BEGIN TRANSACTION'});
try {
  var lock = snowflake.createStatement({
    sqlText: "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION " +
             "SET revision = revision + 1, touched_at = CURRENT_TIMESTAMP() " +
             "WHERE lock_name = 'V1_WRITES'"
  });
  lock.execute();
  if (lock.getNumRowsAffected() !== 1) throw new Error('SERIALIZATION_ROW_MISSING');

  var existing = query(
    'SELECT run_id, resource_key, catalog_dataset_id, catalog_resource_id, ' +
    'evidence_snapshot_id, outcome, reason_code, ' +
    'SHA2(TO_JSON(decision_record), 256) ' +
    'FROM DATASET_DISCOVERY.CANDIDATE_OUTCOMES WHERE operation_key = ?',
    [r.operation_key]
  );
  if (existing.next()) {
    var same = existing.getColumnValue(1) === r.run_id &&
      existing.getColumnValue(2) === r.resource_key &&
      existing.getColumnValue(3) === r.catalog_dataset_id &&
      existing.getColumnValue(4) === r.catalog_resource_id &&
      existing.getColumnValue(5) === r.evidence_snapshot_id &&
      existing.getColumnValue(6) === r.outcome &&
      existing.getColumnValue(7) === r.reason_code &&
      existing.getColumnValue(8) === decision_hash;
    if (existing.next()) throw new Error('DUPLICATE_OPERATION_KEY_STATE');
    if (!same) throw new Error('CONFLICTING_OPERATION_REPLAY');
    snowflake.execute({sqlText: 'COMMIT'});
    return r;
  }

  var run = query(
    'SELECT status, evidence_snapshot_id FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?',
    [r.run_id]
  );
  if (!run.next()) throw new Error('RUN_MISSING');
  var status = run.getColumnValue(1);
  var snapshot = run.getColumnValue(2);
  if (run.next()) throw new Error('DUPLICATE_RUN_ID_STATE');
  if (status !== 'RUNNING') throw new Error('RUN_ALREADY_TERMINAL');
  if (snapshot !== r.evidence_snapshot_id) throw new Error('SNAPSHOT_MISMATCH');

  var candidate = query(
    'SELECT catalog_dataset_id, catalog_resource_id ' +
    'FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY ' +
    'WHERE discovery_run_id = ? AND resource_key = ?',
    [r.evidence_snapshot_id, r.resource_key]
  );
  if (!candidate.next()) throw new Error('CANDIDATE_NOT_IN_SNAPSHOT');
  var same_identity = candidate.getColumnValue(1) === r.catalog_dataset_id &&
    candidate.getColumnValue(2) === r.catalog_resource_id;
  if (candidate.next()) throw new Error('DUPLICATE_CANDIDATE_IDENTITY_STATE');
  if (!same_identity) throw new Error('CANDIDATE_IDENTITY_MISMATCH');

  var duplicate = query(
    'SELECT outcome_id FROM DATASET_DISCOVERY.CANDIDATE_OUTCOMES ' +
    'WHERE run_id = ? AND resource_key = ?', [r.run_id, r.resource_key]
  );
  if (duplicate.next()) throw new Error('CANDIDATE_ALREADY_RECORDED');
  var recommended = query(
    'SELECT recommendation_version_id FROM DATASET_DISCOVERY.RECOMMENDATIONS ' +
    'WHERE run_id = ? AND resource_key = ? AND commit_complete = TRUE',
    [r.run_id, r.resource_key]
  );
  if (recommended.next()) throw new Error('CANDIDATE_ALREADY_RECOMMENDED');

  query(
    'INSERT INTO DATASET_DISCOVERY.CANDIDATE_OUTCOMES (' +
    'outcome_id, operation_key, run_id, resource_key, catalog_dataset_id, ' +
    'catalog_resource_id, evidence_snapshot_id, outcome, reason_code, decision_record) ' +
    'SELECT LOWER(SHA2(?, 256)), ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?)',
    [r.operation_key, r.operation_key, r.run_id, r.resource_key,
     r.catalog_dataset_id, r.catalog_resource_id, r.evidence_snapshot_id,
     r.outcome, r.reason_code, r.decision_record === null ? 'null' : JSON.stringify(r.decision_record)]
  );
  snowflake.execute({sqlText: 'COMMIT'});
  return r;
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;

GRANT OWNERSHIP ON PROCEDURE DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME(VARCHAR)
  TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER COPY CURRENT GRANTS;
