# Surveillance coverage derived result v1

Status: Internal DEV implementation for Story #171; no public or PROD release
Owner: Atlas data stewardship and engineering
Contract version: `surveillance-coverage-result-v1`
Methodology: [`surveillance-coverage-v1`](surveillance-coverage-v1.md)

## Placement and existing-storage gap

The canonical tick contract and governed RAW/STAGING/CONFORMED relations describe
source observations. Coverage state is derived from a canonical observation and
an approved source context, so it cannot be stored as a source observation.
`PRESENTATION.INFECTED_TICK_DERIVED_RESULTS` (Story #169) is metric-specific:
its columns and validation require M1/M2, numeric result state, units, and
numerators/denominators. It cannot hold four categorical coverage constructs.
The existing county `SEMANTIC_OBSERVATIONS` release has fixed county source and
row-count rules and a live release pointer. It cannot represent native NEON
SITE_EVENT evidence without changing published meaning. Story #188 owns the
general semantic ontology; this store adds no registry, public view, or API.

V101 therefore creates only
`PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS` in DEV. The existing DEV
runtime role has SELECT/INSERT; the DEV read role has SELECT. It is separate
from source tables, #169 metric storage, and the county release. There is no
PROD migration, publication pointer, or browser read path.

## Evaluator inputs and state boundaries

`evaluate_surveillance_coverage` accepts exactly one of the four #170
construct IDs, canonical observations, and explicit source context. Active
constructs accept at most one canonical native event/test record. An absent
active row is `UNKNOWN`; it does not become an unsampled event. Collection,
effort, and testing states retain native event/test dates and method scope.
Positive states require structural and provenance quality plus their own
method/effort/testing evidence. Other quality UNKNOWN and NOT_APPLICABLE
components remain explanations, not weights. M1 life-stage resolution is not a
requirement for testing-denominator availability.

County evaluation accepts canonical county and a separate reported taxon or
pathogen target. `source_family` distinguishes the CDC vector and pathogen
workbooks; `source_dataset_id`, `source_version_id`, and `source_vintage` retain
the exact approved source. A valid source context also requires `approved` and
`available`. To assert any county representation state, the caller must supply
an approved publisher scope, canonical eligible universe, `snapshot_complete`,
`scope_approved`, retained `snapshot_evidence_id`, matching
`snapshot_source_version_id`, `publisher_scope_version`, and
`canonical_universe_version`, plus `cumulative_through_date`. Distinct reconciled
canonical county identity is used; duplicate identical rows collapse. Different
source records, statuses, or revisions for the same county remain `UNKNOWN`.
`NO_RECORDS` is a publisher status, never biological absence.

**Current evidence limit:** the existing county semantic release checks its
own source completeness, but the repository does not expose one governed,
versioned, publisher-scoped canonical universe plus independently approved
complete CDC snapshot marker to this evaluator. The code can express
`NOT_REPORTED_IN_DATASET` when that context is supplied and tested synthetically;
current source-backed omission claims are withheld until a steward-approved
scope/universe/version and complete-snapshot evidence ID can be supplied.
Passing an empty query or partial row list is insufficient. No national county
denominator or percentage is introduced.

## Result and identity

The internal result carries construct, methodology/calculation versions,
categorical state, reason codes, native grain, source/version/vintage, exact
canonical and source-record IDs, relevant county/site/plot/event/test identity,
time and scientific/method dimensions, source geography, contextual county
relationship, quality propagation, limitations, and internal artifact lineage.
County status remains `CUMULATIVE_THROUGH_DATE`; active results are point
observations. Site results always retain `NOT_COUNTY_REPRESENTATIVE`.

`coverage_identity` hashes the construct, methodology, exact source version,
county or source event, date, relevant dimensions, canonical input and source
record IDs, source revision, and county snapshot evidence ID where applicable.
The safe scientific projection plus calculation version determines
`result_revision` and `result_id`. Identical calculation produces identical IDs.
Changed scientific or evidence identity produces a distinct revision. Unreviewed
methodology/calculation versions fail closed. V101 retains all staged versions;
it never updates or deletes history. Identical replay is a no-op and a changed
payload for one result ID fails closed. Snowflake standard-table primary keys
are informational, so the intended runtime writer must serialize writes.

`serialize_surveillance_coverage` uses an allowlist. It retains safe source,
version, run, retrieval, normalization-rule, and canonical lineage, plus the
quality and limitation envelope. It excludes artifact IDs/URIs, signed URLs,
raw payloads, restricted workbook content, and credentials, and rejects URL or
credential-like values inside allowed fields. Evidence basis is explicitly
`SYNTHETIC_FIXTURE` or `CURRENT_CODE_SOURCE_BACKED_REPLAY`; the latter requires
actual replay proof from its caller. Historical #162 NEON ingestion alone does
not confer that claim.

## Consumer interpretation and evidence layers

The safe profile is machine-readable and works in a non-map table: list
construct, state, source/version, county or site/event, date semantics,
reason/limitation codes, and quality details. Compare only like constructs and
source/method strata. No numeric coverage score, percentage, county active
aggregate, temporal continuity, M1/M2 input, or #172 rank exists.
Four synthetic safe projection examples are in
[`examples/surveillance-coverage-v1-safe-examples.json`](examples/surveillance-coverage-v1-safe-examples.json).

The test suite exercises independently specified #170 synthetic expectations.
The protected DEV verifier stages one synthetic `SAMPLED_EVENT`, checks replay
and read-back under `OH_LYME_DEV_RUNTIME`, and labels the result fixture-only.
Historical #162 governed NEON canonical ingestion is separate source-backed
evidence; synthetic DEV persistence does not establish a current-code
source-backed coverage profile. The existing county semantic release and
current county score are untouched by the evaluator, serializer, V101, and
verifier. #172 may consume categorical components later only after its own
reviewed prioritization method; this contract does not provide one.
