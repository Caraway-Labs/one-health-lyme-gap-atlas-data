-- DEV-only forward repair for the live SP_CREATE_RUN NULL retry bind failure.
-- V107 remains immutable in the migration ledger. The existing procedure
-- grants and dedicated owner are restored after replacement.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_CREATE_RUN(
  P_OPERATION_KEY VARCHAR,
  P_REQUESTED_RUN_ID VARCHAR,
  P_RETRY_OF_RUN_ID VARCHAR,
  P_METADATA_JSON VARCHAR
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
var retry_of_run_id = optional(P_RETRY_OF_RUN_ID, 200, 'RETRY_ID');
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
    if (original_retry !== retry_of_run_id ||
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
  if (retry_of_run_id !== null) {
    var prior = query(
      'SELECT status FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?', [retry_of_run_id]
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
    [P_REQUESTED_RUN_ID, P_OPERATION_KEY, retry_of_run_id, m.mode, m.trigger_type,
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
    retry_of_run_id: retry_of_run_id,
    request_fingerprint: m.request_fingerprint
  };
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;

GRANT OWNERSHIP ON PROCEDURE DATASET_DISCOVERY.SP_CREATE_RUN(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER COPY CURRENT GRANTS;
