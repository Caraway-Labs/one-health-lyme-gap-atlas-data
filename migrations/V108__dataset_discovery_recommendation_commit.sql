-- Data #449. Draft only: ADR 0041 ownership/grants and protected migration review precede application.
-- One procedure commits an immutable recommendation version, all evidence rows,
-- and inactive search proposals in one serialized DML transaction.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_COMMIT_RECOMMENDATION(P_REQUEST_JSON VARCHAR)
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
function object(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('INVALID_' + label);
  }
  return value;
}
function list(value, maximum, label) {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new Error('INVALID_' + label);
  }
  return value;
}
function query(sql, binds) {
  return snowflake.createStatement({sqlText: sql, binds: binds}).execute();
}
function canonical(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    var items = [];
    for (var a = 0; a < value.length; a++) items.push(canonical(value[a]));
    return '[' + items.join(',') + ']';
  }
  var keys = Object.keys(value).sort();
  var pairs = [];
  for (var k = 0; k < keys.length; k++) {
    pairs.push(JSON.stringify(keys[k]) + ':' + canonical(value[keys[k]]));
  }
  return '{' + pairs.join(',') + '}';
}
function sha256(value) {
  var rows = query('SELECT LOWER(SHA2(?, 256))', [value]);
  if (!rows.next()) throw new Error('HASH_UNAVAILABLE');
  return rows.getColumnValue(1);
}
function sameArray(left, right) {
  if (!Array.isArray(left) || left.length !== right.length) return false;
  for (var i = 0; i < right.length; i++) if (left[i] !== right[i]) return false;
  return true;
}

required(P_REQUEST_JSON, 262144, 'REQUEST');
var r = object(JSON.parse(P_REQUEST_JSON), 'REQUEST_OBJECT');
var top = {
  operation_key: true, identity: true, evidence_snapshot_id: true,
  rights_state: true, assertion_sha256: true, analysis: true,
  ranking_input: true, priority: true, relationship: true, rationale: true
};
for (var key in r) {
  if (Object.prototype.hasOwnProperty.call(r, key) &&
      !Object.prototype.hasOwnProperty.call(top, key)) {
    throw new Error('UNEXPECTED_REQUEST_FIELD');
  }
}
var id = object(r.identity, 'IDENTITY');
var analysis = object(r.analysis, 'ANALYSIS');
var candidate = object(analysis.identity, 'CANDIDATE_IDENTITY');
var ranking = object(r.ranking_input, 'RANKING_INPUT');
var priority = object(r.priority, 'PRIORITY');
var relation = object(r.relationship, 'RELATIONSHIP');
var dimensions = object(ranking.dimensions, 'DIMENSIONS');
required(r.operation_key, 700, 'OPERATION_KEY');
required(id.recommendation_id, 64, 'RECOMMENDATION_ID');
required(id.recommendation_version_id, 64, 'VERSION_ID');
required(id.run_id, 200, 'RUN_ID');
required(id.resource_key, 500, 'RESOURCE_KEY');
required(candidate.catalog_dataset_id, 200, 'CATALOG_DATASET_ID');
required(candidate.catalog_resource_id, 200, 'CATALOG_RESOURCE_ID');
required(r.evidence_snapshot_id, 200, 'SNAPSHOT_ID');
required(r.rationale, 10000, 'RATIONALE');
if (r.operation_key !== 'recommendation:' + id.run_id + ':' + id.resource_key ||
    candidate.resource_key !== id.resource_key ||
    ranking.resource_key !== id.resource_key ||
    ranking.recommendation_version_id !== id.recommendation_version_id ||
    ranking.relationship !== relation.relationship) {
  throw new Error('RECOMMENDATION_IDENTITY_MISMATCH');
}
var delimiter = String.fromCharCode(31);
if (sha256('recommendation-v1' + delimiter + id.resource_key) !==
    id.recommendation_id ||
    sha256('recommendation-version-v1' + delimiter + id.run_id +
           delimiter + id.resource_key) !== id.recommendation_version_id) {
  throw new Error('NONCANONICAL_RECOMMENDATION_ID');
}
if (id.equivalent_to_version_id === undefined) id.equivalent_to_version_id = null;
if (id.equivalent_to_version_id !== null) {
  required(id.equivalent_to_version_id, 64, 'EQUIVALENT_VERSION_ID');
  if (id.equivalent_to_version_id === id.recommendation_version_id) {
    throw new Error('SELF_EQUIVALENCE');
  }
}
if (!/^[0-9a-f]{64}$/.test(required(r.assertion_sha256, 64, 'ASSERTION_HASH'))) {
  throw new Error('INVALID_ASSERTION_HASH');
}
if (r.rights_state !== 'RIGHTS_UNKNOWN' &&
    r.rights_state !== 'RIGHTS_REVIEW_REQUIRED') {
  throw new Error('RUNTIME_CANNOT_ASSERT_RIGHTS_CLEARANCE');
}
if (analysis.classification !== 'RELEVANT' &&
    analysis.classification !== 'POSSIBLY_RELEVANT') {
  throw new Error('INELIGIBLE_CLASSIFICATION');
}
if (['EXACT_DUPLICATE', 'ALREADY_KNOWN'].indexOf(relation.relationship) >= 0 ||
    ranking.identity_valid !== true || ranking.evidence_sufficient !== true) {
  throw new Error('INELIGIBLE_RELATIONSHIP_OR_EVIDENCE');
}
if (priority.formula_version !== 'recommendation-priority-v1' ||
    ['HIGH', 'MEDIUM', 'LOW'].indexOf(priority.bucket) < 0 ||
    typeof priority.score !== 'number' || priority.score < 0 ||
    priority.score > 42 || Math.floor(priority.score) !== priority.score ||
    priority.abstain_reason !== null ||
    typeof priority.missing_count !== 'number' ||
    priority.missing_count < 0 || priority.missing_count > 8 ||
    typeof priority.relationship_adjustment !== 'number') {
  throw new Error('INVALID_PRIORITY');
}
var facts = list(analysis.observed_facts, 100, 'OBSERVED_FACTS');
if (facts.length < 1) throw new Error('EVIDENCE_REQUIRED');
var proposals = list(analysis.search_expansion_proposals, 10, 'SEARCH_PROPOSALS');
list(analysis.inferences, 100, 'INFERENCES');
list(analysis.unknowns, 100, 'UNKNOWNS');
list(analysis.rationale_claims, 30, 'RATIONALE_CLAIMS');
var ids = list(ranking.observed_evidence_ids, 100, 'EVIDENCE_IDS').slice().sort();
var unique_ids = [];
var fact_keys = {};
for (var f = 0; f < facts.length; f++) {
  var fact = object(facts[f], 'OBSERVED_FACT');
  var evidence = object(fact.evidence, 'EVIDENCE_REF');
  required(fact.field, 120, 'FIELD');
  required(fact.value, 500, 'VALUE');
  required(evidence.observation_id, 200, 'OBSERVATION_ID');
  if (evidence.catalog_dataset_id !== candidate.catalog_dataset_id ||
      evidence.catalog_resource_id !== candidate.catalog_resource_id) {
    throw new Error('EVIDENCE_CANDIDATE_MISMATCH');
  }
  var fact_key = evidence.observation_id + delimiter + fact.field;
  if (Object.prototype.hasOwnProperty.call(fact_keys, fact_key)) {
    throw new Error('DUPLICATE_OBSERVED_FACT');
  }
  fact_keys[fact_key] = true;
  if (unique_ids.indexOf(evidence.observation_id) < 0) {
    unique_ids.push(evidence.observation_id);
  }
}
unique_ids.sort();
if (!sameArray(ids, unique_ids)) throw new Error('RANKING_EVIDENCE_MISMATCH');
if (['MIRROR', 'ALTERNATE_DISTRIBUTION', 'REVISION', 'SUPERSESSION',
     'COMPLEMENTARY', 'DISTINCT', 'UNKNOWN'].indexOf(relation.relationship) < 0) {
  throw new Error('INVALID_RELATIONSHIP');
}
required(relation.basis, 200, 'RELATIONSHIP_BASIS');
var relation_citations = list(
  relation.supporting_observation_ids, 100, 'RELATIONSHIP_EVIDENCE'
);
for (var relation_index = 0; relation_index < relation_citations.length;
     relation_index++) {
  if (unique_ids.indexOf(relation_citations[relation_index]) < 0) {
    throw new Error('RELATIONSHIP_EVIDENCE_MISMATCH');
  }
}
var weights = {
  relevance: 5, geography: 3, variables: 4, time: 2,
  provenance: 3, freshness: 1, rights_clarity: 1, complementarity: 2
};
var base = 0;
var missing = 0;
if (Object.keys(dimensions).length !== Object.keys(weights).length) {
  throw new Error('INVALID_DIMENSIONS');
}
for (var dimension_name in weights) {
  var dimension = object(dimensions[dimension_name], 'DIMENSION');
  var value = dimension.value;
  var citations = list(dimension.supporting_observation_ids, 100, 'DIMENSION_CITATIONS');
  if (value === null) {
    missing++;
    if (citations.length) throw new Error('UNKNOWN_DIMENSION_CITES_EVIDENCE');
  } else {
    if (typeof value !== 'number' || Math.floor(value) !== value ||
        value < 0 || value > 2 || citations.length < 1) {
      throw new Error('INVALID_DIMENSION_VALUE');
    }
    base += weights[dimension_name] * value;
  }
  for (var citation_index = 0; citation_index < citations.length; citation_index++) {
    if (unique_ids.indexOf(citations[citation_index]) < 0) {
      throw new Error('DIMENSION_EVIDENCE_MISMATCH');
    }
  }
}
if (dimensions.relevance.value === null || dimensions.relevance.value === 0) {
  throw new Error('INELIGIBLE_RELEVANCE');
}
var adjustment = relation.relationship === 'UNKNOWN' ? -2 : 0;
var calculated_score = Math.max(0, base - 2 * missing + adjustment);
var calculated_bucket = calculated_score >= 30 ? 'HIGH' :
  (calculated_score >= 18 ? 'MEDIUM' : 'LOW');
if (relation.relationship === 'MIRROR' ||
    relation.relationship === 'ALTERNATE_DISTRIBUTION') {
  calculated_bucket = 'LOW';
}
var bucket_order = {HIGH: 0, MEDIUM: 1, LOW: 2};
var calculated_sort_key = [
  0, bucket_order[calculated_bucket], -calculated_score, missing,
  id.resource_key, id.recommendation_version_id
];
if (priority.score !== calculated_score || priority.bucket !== calculated_bucket ||
    priority.missing_count !== missing ||
    priority.relationship_adjustment !== adjustment ||
    !sameArray(priority.sort_key, calculated_sort_key)) {
  throw new Error('PRIORITY_FORMULA_MISMATCH');
}
if ((r.rights_state === 'RIGHTS_REVIEW_REQUIRED') !==
    facts.some(function (fact) {
      return fact.field === 'license' || fact.field === 'access_level';
    })) {
  throw new Error('RIGHTS_EVIDENCE_STATE_MISMATCH');
}
var proposal_ids = [];
for (var p = 0; p < proposals.length; p++) {
  var proposal = object(proposals[p], 'SEARCH_PROPOSAL');
  required(proposal.proposed_term, 120, 'PROPOSED_TERM');
  required(proposal.catalog_scope, 120, 'CATALOG_SCOPE');
  required(proposal.rationale, 500, 'PROPOSAL_RATIONALE');
  var supports = list(proposal.supporting_observation_ids, 100, 'PROPOSAL_EVIDENCE');
  if (supports.length < 1) throw new Error('PROPOSAL_EVIDENCE_REQUIRED');
  for (var s = 0; s < supports.length; s++) {
    if (unique_ids.indexOf(supports[s]) < 0) throw new Error('PROPOSAL_EVIDENCE_MISMATCH');
  }
  proposal_ids.push(id.recommendation_version_id + ':proposal:' + p);
}
var hash_ranking = JSON.parse(JSON.stringify(ranking));
hash_ranking.observed_evidence_ids = ids;
var expected_hash = sha256(canonical({
  analysis: analysis, ranking_input: hash_ranking, priority: priority,
  relationship: relation
}));
if (expected_hash !== r.assertion_sha256) throw new Error('ASSERTION_HASH_MISMATCH');
var receipt = {
  operation_key: r.operation_key,
  identity: id,
  assertion_sha256: r.assertion_sha256,
  evidence_observation_ids: unique_ids,
  proposal_ids: proposal_ids
};

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
    'SELECT recommendation_id, recommendation_version_id, run_id, resource_key, ' +
    'evidence_snapshot_id, assertion_sha256, rights_state, rationale, commit_complete ' +
    'FROM DATASET_DISCOVERY.RECOMMENDATIONS WHERE operation_key = ?', [r.operation_key]
  );
  if (existing.next()) {
    var same = existing.getColumnValue(1) === id.recommendation_id &&
      existing.getColumnValue(2) === id.recommendation_version_id &&
      existing.getColumnValue(3) === id.run_id &&
      existing.getColumnValue(4) === id.resource_key &&
      existing.getColumnValue(5) === r.evidence_snapshot_id &&
      existing.getColumnValue(6) === r.assertion_sha256 &&
      existing.getColumnValue(7) === r.rights_state &&
      existing.getColumnValue(8) === r.rationale &&
      existing.getColumnValue(9) === true;
    if (existing.next()) throw new Error('DUPLICATE_OPERATION_KEY_STATE');
    if (!same) throw new Error('CONFLICTING_OPERATION_REPLAY');
    var prior = query(
      'SELECT evidence_observation_ids, proposal_ids ' +
      'FROM DATASET_DISCOVERY.V_RECOMMENDATION_RECEIPTS WHERE operation_key = ?',
      [r.operation_key]
    );
    if (!prior.next() ||
        !sameArray(prior.getColumnValue(1), unique_ids) ||
        !sameArray(prior.getColumnValue(2) || [], proposal_ids) ||
        prior.next()) {
      throw new Error('INCOMPLETE_RECOMMENDATION_STATE');
    }
    snowflake.execute({sqlText: 'COMMIT'});
    return receipt;
  }

  var run = query(
    'SELECT status, evidence_snapshot_id FROM DATASET_DISCOVERY.RUNS WHERE run_id = ?',
    [id.run_id]
  );
  if (!run.next()) throw new Error('RUN_MISSING');
  var run_status = run.getColumnValue(1);
  var run_snapshot = run.getColumnValue(2);
  if (run.next()) throw new Error('DUPLICATE_RUN_ID_STATE');
  if (run_status !== 'RUNNING') throw new Error('RUN_ALREADY_TERMINAL');
  if (run_snapshot !== r.evidence_snapshot_id) throw new Error('SNAPSHOT_MISMATCH');
  var candidate_rows = query(
    'SELECT catalog_dataset_id, catalog_resource_id ' +
    'FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY ' +
    'WHERE discovery_run_id = ? AND resource_key = ?',
    [r.evidence_snapshot_id, id.resource_key]
  );
  if (!candidate_rows.next()) throw new Error('CANDIDATE_NOT_IN_SNAPSHOT');
  var candidate_same = candidate_rows.getColumnValue(1) === candidate.catalog_dataset_id &&
    candidate_rows.getColumnValue(2) === candidate.catalog_resource_id;
  if (candidate_rows.next()) throw new Error('DUPLICATE_CANDIDATE_IDENTITY_STATE');
  if (!candidate_same) throw new Error('CANDIDATE_IDENTITY_MISMATCH');
  var prior_version = query(
    'SELECT recommendation_version_id FROM DATASET_DISCOVERY.RECOMMENDATIONS ' +
    'WHERE recommendation_version_id = ? OR (run_id = ? AND resource_key = ?)',
    [id.recommendation_version_id, id.run_id, id.resource_key]
  );
  if (prior_version.next()) throw new Error('VERSION_OR_RUN_CANDIDATE_ALREADY_USED');
  var prior_outcome = query(
    'SELECT outcome_id FROM DATASET_DISCOVERY.CANDIDATE_OUTCOMES ' +
    'WHERE run_id = ? AND resource_key = ?', [id.run_id, id.resource_key]
  );
  if (prior_outcome.next()) throw new Error('CANDIDATE_ALREADY_ABSTAINED');
  if (id.equivalent_to_version_id !== null) {
    var equivalent = query(
      'SELECT recommendation_id, run_id FROM DATASET_DISCOVERY.RECOMMENDATIONS ' +
      'WHERE recommendation_version_id = ? AND commit_complete = TRUE',
      [id.equivalent_to_version_id]
    );
    if (!equivalent.next() ||
        equivalent.getColumnValue(1) !== id.recommendation_id ||
        equivalent.getColumnValue(2) === id.run_id || equivalent.next()) {
      throw new Error('INVALID_EQUIVALENT_VERSION');
    }
  }
  for (var e = 0; e < facts.length; e++) {
    var observed = facts[e];
    var ref = observed.evidence;
    var available = query(
      'SELECT field_values, metadata_sha256 FROM ' +
      'DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS ' +
      'WHERE discovery_run_id = ? AND resource_key = ? AND observation_id = ?',
      [r.evidence_snapshot_id, id.resource_key, ref.observation_id]
    );
    if (!available.next()) throw new Error('OBSERVATION_NOT_IN_SNAPSHOT');
    var fields = available.getColumnValue(1);
    var metadata_sha = available.getColumnValue(2);
    if (available.next()) throw new Error('DUPLICATE_OBSERVATION_STATE');
    if (fields === null || fields[observed.field] !== observed.value ||
        (ref.metadata_sha256 !== null &&
         ref.metadata_sha256 !== metadata_sha)) {
      throw new Error('OBSERVED_FACT_NOT_RETAINED');
    }
  }

  query(
    'INSERT INTO DATASET_DISCOVERY.RECOMMENDATIONS (' +
    'recommendation_version_id, recommendation_id, run_id, operation_key, ' +
    'resource_key, catalog_dataset_id, catalog_resource_id, evidence_snapshot_id, ' +
    'assertion_sha256, equivalent_to_version_id, supersedes_version_id, ' +
    'classification, relationship_type, relationship_basis, relationship_uncertainty, ' +
    'rights_state, observed_facts, inferences, unknowns, dimensions, ' +
    'ranking_formula_version, relationship_adjustment, missing_count, ' +
    'priority_score, priority_bucket, rationale, commit_complete) ' +
    'SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?, ' +
    'PARSE_JSON(?), PARSE_JSON(?), PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, ?, ?, ?, TRUE',
    [id.recommendation_version_id, id.recommendation_id, id.run_id, r.operation_key,
     id.resource_key, candidate.catalog_dataset_id, candidate.catalog_resource_id,
     r.evidence_snapshot_id, r.assertion_sha256, id.equivalent_to_version_id,
     analysis.classification, relation.relationship, relation.basis, r.rights_state,
     JSON.stringify(facts), JSON.stringify(analysis.inferences),
     JSON.stringify(analysis.unknowns), JSON.stringify(dimensions),
     priority.formula_version, priority.relationship_adjustment, priority.missing_count,
     priority.score, priority.bucket, r.rationale]
  );
  for (var row = 0; row < facts.length; row++) {
    var item = facts[row];
    var evidence_row = snowflake.createStatement({
      sqlText: 'INSERT INTO DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE (' +
        'recommendation_version_id, observation_id, catalog_dataset_id, ' +
        'catalog_resource_id, field_name, metadata_sha256, observed_at) ' +
        'SELECT ?, observation_id, catalog_dataset_id, catalog_resource_id, ?, ' +
        'metadata_sha256, observed_at ' +
        'FROM DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS ' +
        'WHERE discovery_run_id = ? AND resource_key = ? AND observation_id = ?',
      binds: [id.recommendation_version_id, item.field, r.evidence_snapshot_id,
              id.resource_key, item.evidence.observation_id]
    });
    evidence_row.execute();
    if (evidence_row.getNumRowsAffected() !== 1) throw new Error('EVIDENCE_WRITE_MISMATCH');
  }
  for (var index = 0; index < proposals.length; index++) {
    var search = proposals[index];
    query(
      'INSERT INTO DATASET_DISCOVERY.SEARCH_EXPANSION_PROPOSALS (' +
      'proposal_id, recommendation_version_id, run_id, proposed_term, ' +
      'catalog_scope, evidence_observation_ids, rationale, review_status) ' +
      "SELECT ?, ?, ?, ?, ?, PARSE_JSON(?), ?, 'PENDING'",
      [proposal_ids[index], id.recommendation_version_id, id.run_id,
       search.proposed_term, search.catalog_scope,
       JSON.stringify(search.supporting_observation_ids), search.rationale]
    );
  }
  snowflake.execute({sqlText: 'COMMIT'});
  return receipt;
} catch (error) {
  snowflake.execute({sqlText: 'ROLLBACK'});
  throw error;
}
$$;
