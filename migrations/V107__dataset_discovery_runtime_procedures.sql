-- Data #449. Draft procedure code only: do not apply until #454 and ADR 0041 gates pass.
-- This owner-rights procedure is granted narrowly by a later approved role migration.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_CREATE_RUN(
  P_OPERATION_KEY VARCHAR,
  P_REQUESTED_RUN_ID VARCHAR,
  P_RETRY_OF_RUN_ID VARCHAR,
  P_METADATA_JSON VARCHAR
)
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
function optional(value, maximum, label) {
  if (value === null || value === undefined) return null;
  return required(value, maximum, label);
}
function query(sql, binds) {
  return snowflake.createStatement({sqlText: sql, binds: binds}).execute();
}
function versionMap(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('INVALID_VERSION_MAP');
  }
  var keys = Object.keys(value);
  if (keys.length > 20) throw new Error('VERSION_MAP_TOO_LARGE');
  for (var i = 0; i < keys.length; i++) {
    required(keys[i], 80, 'VERSION_KEY');
    required(value[keys[i]], 200, 'VERSION_VALUE');
  }
}
function canonical(value) {
  if (value === null) return 'null';
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('INVALID_FINGERPRINT_INPUT');
  }
  var keys = Object.keys(value).sort();
  var parts = [];
  for (var i = 0; i < keys.length; i++) {
    parts.push(JSON.stringify(keys[i]) + ':' + canonical(value[keys[i]]));
  }
  return '{' + parts.join(',') + '}';
}

required(P_OPERATION_KEY, 200, 'OPERATION_KEY');
required(P_REQUESTED_RUN_ID, 200, 'RUN_ID');
optional(P_RETRY_OF_RUN_ID, 200, 'RETRY_ID');
required(P_METADATA_JSON, 16384, 'METADATA');
var m = JSON.parse(P_METADATA_JSON);
if (m === null || typeof m !== 'object' || Array.isArray(m)) {
  throw new Error('INVALID_METADATA_OBJECT');
}
var allowed = {
  mode: true, trigger_type: true, code_sha: true, spec_version: true,
  graph_version: true, config_fingerprint: true, search_fingerprint: true,
  evidence_snapshot_id: true, provider: true, model_id: true,
  model_fingerprint: true, prompt_versions: true, tool_versions: true,
  eval_version: true, trace_id: true, host_session_id: true,
  request_fingerprint: true
};
for (var key in m) {
  if (Object.prototype.hasOwnProperty.call(m, key) &&
      !Object.prototype.hasOwnProperty.call(allowed, key)) {
    throw new Error('UNEXPECTED_METADATA_FIELD');
  }
}
required(m.mode, 40, 'MODE');
required(m.trigger_type, 80, 'TRIGGER');
if (!/^[0-9a-f]{40}$/.test(required(m.code_sha, 40, 'CODE_SHA'))) {
  throw new Error('INVALID_CODE_SHA');
}
required(m.spec_version, 80, 'SPEC_VERSION');
required(m.graph_version, 80, 'GRAPH_VERSION');
if (!/^[0-9a-f]{64}$/.test(required(m.config_fingerprint, 64, 'CONFIG_FINGERPRINT')) ||
    !/^[0-9a-f]{64}$/.test(required(m.search_fingerprint, 64, 'SEARCH_FINGERPRINT')) ||
    !/^[0-9a-f]{64}$/.test(required(m.request_fingerprint, 64, 'REQUEST_FINGERPRINT'))) {
  throw new Error('INVALID_FINGERPRINT');
}
required(m.evidence_snapshot_id, 200, 'SNAPSHOT');
optional(m.provider, 100, 'PROVIDER');
optional(m.model_id, 200, 'MODEL_ID');
optional(m.model_fingerprint, 64, 'MODEL_FINGERPRINT');
optional(m.eval_version, 100, 'EVAL_VERSION');
optional(m.trace_id, 200, 'TRACE_ID');
optional(m.host_session_id, 200, 'HOST_SESSION_ID');
versionMap(m.prompt_versions);
versionMap(m.tool_versions);
var identity = {};
for (var identity_key in allowed) {
  if (identity_key !== 'trace_id' && identity_key !== 'host_session_id' &&
      identity_key !== 'request_fingerprint') {
    if (!Object.prototype.hasOwnProperty.call(m, identity_key)) {
      throw new Error('MISSING_FINGERPRINT_FIELD');
    }
    identity[identity_key] = m[identity_key];
  }
}
var digest = query('SELECT LOWER(SHA2(?, 256))', [canonical(identity)]);
if (!digest.next() || digest.getColumnValue(1) !== m.request_fingerprint) {
  throw new Error('REQUEST_FINGERPRINT_MISMATCH');
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
    'SELECT run_id, retry_of_run_id, request_fingerprint FROM DATASET_DISCOVERY.RUNS ' +
    'WHERE operation_key = ?', [P_OPERATION_KEY]
  );
  if (existing.next()) {
    var original_run_id = existing.getColumnValue(1);
    var original_retry = existing.getColumnValue(2);
    var original_fingerprint = existing.getColumnValue(3);
    if (existing.next()) throw new Error('DUPLICATE_OPERATION_KEY_STATE');
    if (original_retry !== P_RETRY_OF_RUN_ID ||
        original_fingerprint !== m.request_fingerprint) {
      throw new Error('CONFLICTING_OPERATION_REPLAY');
    }
    snowflake.execute({sqlText: 'COMMIT'});
    return {
      run_id: original_run_id,
      operation_key: P_OPERATION_KEY,
      retry_of_run_id: original_retry,
      request_fingerprint: original_fingerprint
    };
  }

  var duplicate_id = query(
    'SELECT run_id FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?', [P_REQUESTED_RUN_ID]
  );
  if (duplicate_id.next()) throw new Error('RUN_ID_ALREADY_USED');
  if (P_RETRY_OF_RUN_ID !== null) {
    var prior = query(
      'SELECT status FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?', [P_RETRY_OF_RUN_ID]
    );
    if (!prior.next()) throw new Error('RETRY_PARENT_MISSING');
    var prior_status = prior.getColumnValue(1);
    if (prior.next()) throw new Error('DUPLICATE_RETRY_PARENT_STATE');
    if (['FAILED', 'PARTIAL', 'BUDGET_STOPPED', 'CANCELLED'].indexOf(prior_status) < 0) {
      throw new Error('RETRY_PARENT_NOT_TERMINAL');
    }
  }

  query(
    'INSERT INTO DATASET_DISCOVERY.RUNS (' +
    'run_id, operation_key, retry_of_run_id, mode, trigger_type, status, started_at, ' +
    'code_sha, spec_version, graph_version, config_fingerprint, search_fingerprint, ' +
    'evidence_snapshot_id, provider, model_id, model_fingerprint, prompt_versions, ' +
    'tool_versions, eval_version, trace_id, host_session_id, request_fingerprint) ' +
    'SELECT ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ' +
    'PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, ?',
    [P_REQUESTED_RUN_ID, P_OPERATION_KEY, P_RETRY_OF_RUN_ID, m.mode, m.trigger_type,
     'RUNNING',
     m.code_sha, m.spec_version, m.graph_version, m.config_fingerprint,
     m.search_fingerprint, m.evidence_snapshot_id, m.provider, m.model_id,
     m.model_fingerprint, JSON.stringify(m.prompt_versions), JSON.stringify(m.tool_versions),
     m.eval_version, m.trace_id, m.host_session_id, m.request_fingerprint]
  );
  snowflake.execute({sqlText: 'COMMIT'});
  return {
    run_id: P_REQUESTED_RUN_ID,
    operation_key: P_OPERATION_KEY,
    retry_of_run_id: P_RETRY_OF_RUN_ID,
    request_fingerprint: m.request_fingerprint
  };
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_FINALIZE_RUN(P_REQUEST_JSON VARCHAR)
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
function nonnegativeInteger(value) {
  return typeof value === 'number' && isFinite(value) &&
    Math.floor(value) === value && value >= 0;
}
required(P_REQUEST_JSON, 4096, 'REQUEST');
var r = JSON.parse(P_REQUEST_JSON);
if (r === null || typeof r !== 'object' || Array.isArray(r)) {
  throw new Error('INVALID_REQUEST_OBJECT');
}
var allowed = {
  operation_key: true, run_id: true, status: true, processed_count: true,
  recommendation_count: true, budget_usage: true, stop_reason: true
};
for (var key in r) {
  if (Object.prototype.hasOwnProperty.call(r, key) &&
      !Object.prototype.hasOwnProperty.call(allowed, key)) {
    throw new Error('UNEXPECTED_REQUEST_FIELD');
  }
}
required(r.operation_key, 200, 'OPERATION_KEY');
required(r.run_id, 200, 'RUN_ID');
if (['SUCCEEDED_WITH_RECOMMENDATIONS', 'SUCCEEDED_NO_NEW_CANDIDATES',
     'PARTIAL', 'BUDGET_STOPPED', 'FAILED', 'CANCELLED'].indexOf(r.status) < 0) {
  throw new Error('INVALID_FINAL_STATUS');
}
if (!nonnegativeInteger(r.processed_count) || r.processed_count > 100 ||
    !nonnegativeInteger(r.recommendation_count) ||
    r.recommendation_count > r.processed_count) {
  throw new Error('INVALID_FINAL_COUNTS');
}
if (r.stop_reason === undefined) r.stop_reason = null;
if (r.stop_reason !== null) required(r.stop_reason, 200, 'STOP_REASON');
if (r.budget_usage === null || typeof r.budget_usage !== 'object' ||
    Array.isArray(r.budget_usage)) throw new Error('INVALID_BUDGET_USAGE');
var usage_fields = {
  candidates: true, pages: true, graph_steps: true, model_calls: true,
  tool_calls: true, elapsed_seconds: true, input_tokens: true,
  output_tokens: true, evidence_bytes: true, retained_state_bytes: true,
  estimated_spend_cents: true
};
for (var usage_key in r.budget_usage) {
  if (!Object.prototype.hasOwnProperty.call(usage_fields, usage_key) ||
      !nonnegativeInteger(r.budget_usage[usage_key])) {
    throw new Error('INVALID_BUDGET_USAGE');
  }
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

  var run = query(
    'SELECT status, finalization_operation_key, counters:processed_count::NUMBER, ' +
    'counters:recommendation_count::NUMBER, stop_reason, counters:budget_usage ' +
    'FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?', [r.run_id]
  );
  if (!run.next()) throw new Error('RUN_MISSING');
  var prior_status = run.getColumnValue(1);
  var prior_key = run.getColumnValue(2);
  var prior_processed = run.getColumnValue(3);
  var prior_recommendations = run.getColumnValue(4);
  var prior_stop_reason = run.getColumnValue(5);
  var prior_usage = run.getColumnValue(6);
  if (run.next()) throw new Error('DUPLICATE_RUN_ID_STATE');
  if (prior_key !== null) {
    var usage_same = prior_usage !== null &&
      Object.keys(prior_usage).length === Object.keys(r.budget_usage).length;
    if (usage_same) {
      for (var counter in r.budget_usage) {
        if (prior_usage[counter] !== r.budget_usage[counter]) usage_same = false;
      }
    }
    if (prior_key !== r.operation_key || prior_status !== r.status ||
        prior_processed !== r.processed_count ||
        prior_recommendations !== r.recommendation_count ||
        prior_stop_reason !== r.stop_reason || !usage_same) {
      throw new Error('CONFLICTING_FINALIZATION_REPLAY');
    }
    snowflake.execute({sqlText: 'COMMIT'});
    return r;
  }
  if (prior_status !== 'RUNNING') throw new Error('RUN_ALREADY_TERMINAL');

  var outcomes = query(
    'SELECT COUNT(*) FROM DATASET_DISCOVERY.CANDIDATE_OUTCOMES WHERE run_id = ?',
    [r.run_id]
  );
  outcomes.next();
  var outcome_count = outcomes.getColumnValue(1);
  var recommendations = query(
    'SELECT COUNT(*) FROM DATASET_DISCOVERY.RECOMMENDATIONS ' +
    'WHERE run_id = ? AND commit_complete = TRUE', [r.run_id]
  );
  recommendations.next();
  var recommendation_count = recommendations.getColumnValue(1);
  if (r.processed_count !== outcome_count + recommendation_count ||
      r.recommendation_count !== recommendation_count) {
    throw new Error('DURABLE_COUNTER_MISMATCH');
  }
  if ((r.status === 'SUCCEEDED_WITH_RECOMMENDATIONS' && recommendation_count === 0) ||
      (r.status === 'SUCCEEDED_NO_NEW_CANDIDATES' && recommendation_count !== 0)) {
    throw new Error('SUCCESS_STATUS_MISMATCH');
  }

  var update = snowflake.createStatement({
    sqlText: 'UPDATE DATASET_DISCOVERY.RUNS SET status = ?, completed_at = CURRENT_TIMESTAMP(), ' +
      "counters = OBJECT_CONSTRUCT('processed_count', ?, 'recommendation_count', ?, " +
      "'budget_usage', PARSE_JSON(?)), " +
      'stop_reason = ?, finalization_operation_key = ? WHERE run_id = ? AND status = \'RUNNING\'',
    binds: [r.status, r.processed_count, r.recommendation_count,
            JSON.stringify(r.budget_usage), r.stop_reason, r.operation_key, r.run_id]
  });
  update.execute();
  if (update.getNumRowsAffected() !== 1) throw new Error('RUN_FINALIZATION_RACE');
  snowflake.execute({sqlText: 'COMMIT'});
  return r;
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME(
  P_REQUEST_JSON VARCHAR
)
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
required(P_REQUEST_JSON, 4096, 'REQUEST');
var r = JSON.parse(P_REQUEST_JSON);
if (r === null || typeof r !== 'object' || Array.isArray(r)) {
  throw new Error('INVALID_REQUEST_OBJECT');
}
var allowed = {
  operation_key: true, run_id: true, resource_key: true,
  catalog_dataset_id: true, catalog_resource_id: true,
  evidence_snapshot_id: true, outcome: true, reason_code: true
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
if (r.reason_code === undefined) r.reason_code = null;
if (r.reason_code !== null &&
    !/^[A-Z][A-Z0-9_]{0,79}$/.test(required(r.reason_code, 80, 'REASON_CODE'))) {
  throw new Error('INVALID_REASON_CODE');
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
    'evidence_snapshot_id, outcome, reason_code ' +
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
      existing.getColumnValue(7) === r.reason_code;
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
    'catalog_resource_id, evidence_snapshot_id, outcome, reason_code) ' +
    'SELECT LOWER(SHA2(?, 256)), ?, ?, ?, ?, ?, ?, ?, ?',
    [r.operation_key, r.operation_key, r.run_id, r.resource_key,
     r.catalog_dataset_id, r.catalog_resource_id, r.evidence_snapshot_id,
     r.outcome, r.reason_code]
  );
  snowflake.execute({sqlText: 'COMMIT'});
  return r;
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;
