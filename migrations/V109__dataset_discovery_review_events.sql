-- Data #449 / Dataset Discovery #9. Draft only: ADR 0041 owner/security approval,
-- READ SESSION and dedicated procedure ownership precede protected application.
USE DATABASE {{ DATABASE }};

ALTER TABLE DATASET_DISCOVERY.REVIEW_EVENTS
  ADD COLUMN IF NOT EXISTS event_sequence NUMBER;
ALTER TABLE DATASET_DISCOVERY.REVIEW_EVENTS
  ADD COLUMN IF NOT EXISTS prior_event_id VARCHAR;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE AS
SELECT rec.recommendation_version_id, rec.recommendation_id, rec.run_id,
       rec.resource_key, rec.rights_state, rec.priority_bucket,
       rec.priority_score, rec.rationale,
       COALESCE(rev.new_state, 'PENDING') AS review_state,
       rev.review_event_id AS latest_review_event_id,
       rev.event_sequence AS latest_event_sequence
FROM DATASET_DISCOVERY.RECOMMENDATIONS rec
LEFT JOIN (
  SELECT recommendation_version_id, review_event_id, new_state, event_sequence
  FROM DATASET_DISCOVERY.REVIEW_EVENTS
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY recommendation_version_id
    ORDER BY event_sequence DESC, review_event_id DESC
  ) = 1
) rev ON rev.recommendation_version_id = rec.recommendation_version_id
WHERE rec.commit_complete = TRUE;

-- Human review can inspect the bounded assertion and references without
-- reading mutable catalog payloads or source-approval tables.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_REVIEW_RECOMMENDATION_DETAIL AS
SELECT rec.recommendation_version_id, rec.recommendation_id, rec.run_id,
       rec.resource_key, rec.catalog_dataset_id, rec.catalog_resource_id,
       rec.evidence_snapshot_id, rec.assertion_sha256,
       rec.classification, rec.relationship_type, rec.relationship_basis,
       rec.rights_state, rec.observed_facts, rec.inferences, rec.unknowns,
       rec.dimensions, rec.ranking_formula_version,
       rec.relationship_adjustment, rec.missing_count,
       rec.priority_score, rec.priority_bucket, rec.rank_in_run,
       rec.rationale, rec.created_at, state.review_state,
       state.latest_review_event_id
FROM DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS rec
JOIN DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE state
  ON state.recommendation_version_id = rec.recommendation_version_id;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_REVIEW_EVIDENCE AS
SELECT evidence.recommendation_version_id, evidence.observation_id,
       evidence.catalog_dataset_id, evidence.catalog_resource_id,
       evidence.field_name, evidence.metadata_sha256,
       evidence.observed_at
FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE evidence
JOIN DATASET_DISCOVERY.RECOMMENDATIONS rec
  ON rec.recommendation_version_id = evidence.recommendation_version_id
WHERE rec.commit_complete = TRUE;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_PENDING_RECOMMENDATIONS AS
SELECT rec.recommendation_version_id, rec.recommendation_id, rec.run_id,
       rec.resource_key, rec.priority_bucket, rec.priority_score,
       rec.rank_in_run, rec.rationale, rec.rights_state, rec.created_at,
       state.review_state, state.latest_review_event_id
FROM DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS rec
JOIN DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE state
  ON state.recommendation_version_id = rec.recommendation_version_id
WHERE state.review_state IN ('PENDING', 'NEEDS_MORE_INFORMATION');

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_RECOMMENDATION_HISTORY AS
SELECT rec.recommendation_id, rec.recommendation_version_id, rec.run_id,
       rec.resource_key, rec.assertion_sha256, rec.equivalent_to_version_id,
       rec.supersedes_version_id, rec.created_at, rev.review_event_id,
       rev.command_key, rev.event_sequence, rev.prior_event_id,
       rev.prior_state, rev.decision, rev.new_state, rev.rationale,
       rev.conditions, rev.reviewer_user, rev.reviewer_role,
       rev.reviewed_at, rev.correction_of_event_id
FROM DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS rec
LEFT JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev
  ON rev.recommendation_version_id = rec.recommendation_version_id
WHERE rec.commit_complete = TRUE;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_ACCEPTED_RECOMMENDATIONS_FOR_HANDOFF AS
SELECT state.recommendation_id, state.recommendation_version_id,
       state.run_id, state.resource_key, rev.review_event_id,
       rev.reviewer_user, state.rights_state
FROM DATASET_DISCOVERY.V_CURRENT_REVIEW_STATE state
JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev
  ON rev.review_event_id = state.latest_review_event_id
WHERE state.review_state = 'ACCEPTED_FOR_INVESTIGATION';

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_REVIEW_EVENT_RECEIPTS AS
SELECT review_event_id, command_key, recommendation_version_id,
       prior_event_id, prior_state, decision, new_state, rationale,
       conditions, reviewer_user, reviewer_role, event_sequence,
       correction_of_event_id, reviewed_at
FROM DATASET_DISCOVERY.REVIEW_EVENTS;

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_APPEND_REVIEW_EVENT(P_REQUEST_JSON VARCHAR)
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
  return value === null ? null : required(value, maximum, label);
}
function query(sql, binds) {
  return snowflake.createStatement({sqlText: sql, binds: binds}).execute();
}
function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return '[' + value.map(canonical).join(',') + ']';
  }
  var keys = Object.keys(value).sort();
  return '{' + keys.map(function (key) {
    return JSON.stringify(key) + ':' + canonical(value[key]);
  }).join(',') + '}';
}
function sha256(value) {
  var result = query('SELECT LOWER(SHA2(?, 256))', [value]);
  if (!result.next()) throw new Error('HASH_UNAVAILABLE');
  return result.getColumnValue(1);
}

required(P_REQUEST_JSON, 8192, 'REQUEST');
var r = JSON.parse(P_REQUEST_JSON);
if (r === null || typeof r !== 'object' || Array.isArray(r)) {
  throw new Error('INVALID_REQUEST_OBJECT');
}
var allowed = {
  command_key: true, recommendation_version_id: true,
  expected_prior_event_id: true, decision: true, rationale: true,
  conditions: true, correction_of_event_id: true
};
for (var key in r) {
  if (Object.prototype.hasOwnProperty.call(r, key) &&
      !Object.prototype.hasOwnProperty.call(allowed, key)) {
    throw new Error('UNEXPECTED_REQUEST_FIELD');
  }
}
required(r.command_key, 200, 'COMMAND_KEY');
required(r.recommendation_version_id, 64, 'VERSION_ID');
required(r.rationale, 2000, 'RATIONALE');
r.expected_prior_event_id = optional(r.expected_prior_event_id, 64, 'PRIOR_EVENT_ID');
r.correction_of_event_id = optional(r.correction_of_event_id, 64, 'CORRECTION_ID');
if (!Array.isArray(r.conditions) || r.conditions.length > 10 ||
    r.conditions.some(function (item) {
      return typeof item !== 'string' || item.length < 1 || item.length > 300;
    })) {
  throw new Error('INVALID_CONDITIONS');
}
var next_state = {
  ACCEPT_FOR_INVESTIGATION: 'ACCEPTED_FOR_INVESTIGATION',
  REJECT: 'REJECTED', MARK_DUPLICATE: 'DUPLICATE',
  MARK_ALREADY_KNOWN: 'ALREADY_KNOWN',
  REQUEST_MORE_INFORMATION: 'NEEDS_MORE_INFORMATION', EXPIRE: 'EXPIRED'
}[r.decision];
if (next_state === undefined) throw new Error('INVALID_REVIEW_DECISION');
var event_id = sha256('review-event-v1' + String.fromCharCode(31) + r.command_key);

// Owner-rights CURRENT_USER/CURRENT_ROLE name the owner context, not the caller.
// This call requires the dedicated non-login procedure owner to hold READ SESSION.
var principal = query(
  "SELECT SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME'), " +
  "SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_TYPE'), " +
  "SYS_CONTEXT('SNOWFLAKE$SESSION', 'ROLE')", []
);
if (!principal.next()) throw new Error('REVIEW_PRINCIPAL_UNAVAILABLE');
var reviewer_user = principal.getColumnValue(1);
var principal_type = principal.getColumnValue(2);
var reviewer_role = principal.getColumnValue(3);
if (principal.next() || principal_type !== 'USER_PERSON' ||
    typeof reviewer_user !== 'string' || reviewer_user.length < 1 ||
    reviewer_user.length > 200 ||
    reviewer_role !== 'OH_LYME_{{ ENV }}_DATASET_DISCOVERY_REVIEWER') {
  throw new Error('UNAUTHORIZED_REVIEW_PRINCIPAL');
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

  var allowlist = query(
    'SELECT reviewer_user FROM DATASET_DISCOVERY.REVIEWER_ALLOWLIST ' +
    'WHERE reviewer_user = ? AND is_active = TRUE', [reviewer_user]
  );
  if (!allowlist.next() || allowlist.next()) throw new Error('REVIEWER_NOT_ALLOWLISTED');

  var existing = query(
    'SELECT review_event_id, recommendation_version_id, prior_event_id, ' +
    'decision, rationale, conditions, correction_of_event_id, reviewer_user, ' +
    'reviewer_role, prior_state, new_state, event_sequence ' +
    'FROM DATASET_DISCOVERY.REVIEW_EVENTS WHERE command_key = ?', [r.command_key]
  );
  if (existing.next()) {
    var same = existing.getColumnValue(1) === event_id &&
      existing.getColumnValue(2) === r.recommendation_version_id &&
      existing.getColumnValue(3) === r.expected_prior_event_id &&
      existing.getColumnValue(4) === r.decision &&
      existing.getColumnValue(5) === r.rationale &&
      canonical(existing.getColumnValue(6)) === canonical(r.conditions) &&
      existing.getColumnValue(7) === r.correction_of_event_id &&
      existing.getColumnValue(8) === reviewer_user &&
      existing.getColumnValue(9) === reviewer_role &&
      existing.getColumnValue(11) === next_state;
    var old_state = existing.getColumnValue(10);
    var old_sequence = existing.getColumnValue(12);
    if (existing.next()) throw new Error('DUPLICATE_REVIEW_COMMAND_STATE');
    if (!same) throw new Error('CONFLICTING_REVIEW_REPLAY');
    snowflake.execute({sqlText: 'COMMIT'});
    return {
      review_event_id: event_id, command_key: r.command_key,
      recommendation_version_id: r.recommendation_version_id,
      prior_event_id: r.expected_prior_event_id,
      prior_state: old_state, new_state: next_state,
      decision: r.decision, reviewer_user: reviewer_user,
      reviewer_role: reviewer_role, event_sequence: old_sequence
    };
  }
  var prior_id = query(
    'SELECT review_event_id FROM DATASET_DISCOVERY.REVIEW_EVENTS ' +
    'WHERE review_event_id = ?', [event_id]
  );
  if (prior_id.next()) throw new Error('REVIEW_EVENT_ID_ALREADY_USED');
  var recommendation = query(
    'SELECT recommendation_version_id, observed_facts, ' +
    'catalog_dataset_id, catalog_resource_id ' +
    'FROM DATASET_DISCOVERY.RECOMMENDATIONS ' +
    'WHERE recommendation_version_id = ? AND commit_complete = TRUE',
    [r.recommendation_version_id]
  );
  if (!recommendation.next()) throw new Error('RECOMMENDATION_VERSION_MISSING');
  var observed_facts = recommendation.getColumnValue(2);
  var catalog_dataset_id = recommendation.getColumnValue(3);
  var catalog_resource_id = recommendation.getColumnValue(4);
  if (recommendation.next()) throw new Error('DUPLICATE_VERSION_STATE');
  if (!Array.isArray(observed_facts) || observed_facts.length < 1 ||
      observed_facts.length > 100) {
    throw new Error('RECOMMENDATION_FACTS_INVALID');
  }
  var expected_evidence = {};
  for (var fact_index = 0; fact_index < observed_facts.length; fact_index++) {
    var fact = observed_facts[fact_index];
    if (fact === null || typeof fact !== 'object' ||
        fact.evidence === null || typeof fact.evidence !== 'object' ||
        typeof fact.field !== 'string' ||
        typeof fact.evidence.observation_id !== 'string' ||
        fact.evidence.catalog_dataset_id !== catalog_dataset_id ||
        fact.evidence.catalog_resource_id !== catalog_resource_id) {
      throw new Error('RECOMMENDATION_FACTS_INVALID');
    }
    var fact_key = fact.evidence.observation_id + String.fromCharCode(31) + fact.field;
    if (Object.prototype.hasOwnProperty.call(expected_evidence, fact_key)) {
      throw new Error('DUPLICATE_RECOMMENDATION_FACT');
    }
    expected_evidence[fact_key] = true;
  }
  var evidence = query(
    'SELECT observation_id, field_name, catalog_dataset_id, catalog_resource_id ' +
    'FROM DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE ' +
    'WHERE recommendation_version_id = ?', [r.recommendation_version_id]
  );
  var actual_evidence = {};
  var evidence_count = 0;
  while (evidence.next()) {
    evidence_count++;
    if (evidence_count > 100) throw new Error('RECOMMENDATION_EVIDENCE_OVERFLOW');
    var evidence_key = evidence.getColumnValue(1) + String.fromCharCode(31) +
      evidence.getColumnValue(2);
    if (!Object.prototype.hasOwnProperty.call(expected_evidence, evidence_key) ||
        Object.prototype.hasOwnProperty.call(actual_evidence, evidence_key) ||
        evidence.getColumnValue(3) !== catalog_dataset_id ||
        evidence.getColumnValue(4) !== catalog_resource_id) {
      throw new Error('RECOMMENDATION_EVIDENCE_MISMATCH');
    }
    actual_evidence[evidence_key] = true;
  }
  if (evidence_count !== observed_facts.length) {
    throw new Error('RECOMMENDATION_EVIDENCE_MISSING');
  }
  var current = query(
    'SELECT review_event_id, new_state FROM DATASET_DISCOVERY.REVIEW_EVENTS ' +
    'WHERE recommendation_version_id = ? ' +
    'ORDER BY event_sequence DESC, review_event_id DESC LIMIT 2',
    [r.recommendation_version_id]
  );
  var prior_event_id = null;
  var prior_state = 'PENDING';
  if (current.next()) {
    prior_event_id = current.getColumnValue(1);
    prior_state = current.getColumnValue(2);
  }
  if (r.expected_prior_event_id !== prior_event_id) {
    throw new Error('STALE_REVIEW_STATE');
  }
  if (prior_state === 'ACCEPTED_FOR_INVESTIGATION') {
    throw new Error('ACCEPTED_REVIEW_IS_TERMINAL');
  }
  if (prior_state !== 'PENDING' && prior_state !== 'NEEDS_MORE_INFORMATION') {
    if (r.correction_of_event_id !== prior_event_id) {
      throw new Error('TERMINAL_REVIEW_REQUIRES_CORRECTION');
    }
  } else if (r.correction_of_event_id !== null) {
    throw new Error('CORRECTION_REQUIRES_TERMINAL_STATE');
  }
  var sequence_result = query(
    "SELECT revision FROM DATASET_DISCOVERY.WRITE_SERIALIZATION " +
    "WHERE lock_name = 'V1_WRITES'", []
  );
  if (!sequence_result.next()) throw new Error('SERIALIZATION_ROW_MISSING');
  var sequence = sequence_result.getColumnValue(1);
  if (sequence_result.next()) throw new Error('DUPLICATE_SERIALIZATION_ROW');
  query(
    'INSERT INTO DATASET_DISCOVERY.REVIEW_EVENTS (' +
    'review_event_id, command_key, recommendation_version_id, prior_event_id, ' +
    'event_sequence, prior_state, new_state, decision, rationale, conditions, ' +
    'reviewer_user, reviewer_role, correction_of_event_id) ' +
    'SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, PARSE_JSON(?), ?, ?, ?',
    [event_id, r.command_key, r.recommendation_version_id, prior_event_id,
     sequence, prior_state, next_state, r.decision, r.rationale,
     JSON.stringify(r.conditions), reviewer_user, reviewer_role,
     r.correction_of_event_id]
  );
  snowflake.execute({sqlText: 'COMMIT'});
  return {
    review_event_id: event_id, command_key: r.command_key,
    recommendation_version_id: r.recommendation_version_id,
    prior_event_id: prior_event_id, prior_state: prior_state,
    new_state: next_state, decision: r.decision,
    reviewer_user: reviewer_user, reviewer_role: reviewer_role,
    event_sequence: sequence
  };
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;
