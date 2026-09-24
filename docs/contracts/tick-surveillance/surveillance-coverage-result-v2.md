# Surveillance coverage safe result v2

Status: Internal DEV remediation candidate for Story #171; no public or PROD release
Owner: Atlas data stewardship and engineering
Schema: `surveillance-coverage-result-v2.schema.json`
Methodology: `surveillance-coverage-v1`
Calculation version: `surveillance-coverage-calculation-v2`

This contract supersedes v1 for new #171 calculations. Historical v1 rows and
their V101 migration remain immutable. The canonical observation contract is
unchanged except for optional explicit testing evidence fields; canonical
county-status rows still require a five-digit FIPS.

`scientific_eligibility` contains one safe, versioned attestation for each
required field. Each attestation records the semantic role, exact publisher,
product and version, registry and mapping rule, canonical ID, safe canonical
label, mapping status, aggregate flag, and eligibility. Approved exact-source
proof is required for a positive state. ID or label inputs normalize to the
same canonical ID; a globally valid value without exact-source proof is
ineligible. Labels are display metadata, never scientific keys.

Positive states also require an approved
publisher/source/version/vintage/construct tuple in
`surveillance-scientific-eligibility-v1.json`. Unknown, mixed, aggregate,
unlisted, or source-incompatible vintage cannot establish a positive state.
For active collection, `POINT_IN_TIME` must be explicit; `PERIOD` is retained
as safe `UNKNOWN`/`UNAVAILABLE` evidence without a positive state. A positive
numeric effort and `missingness.collection_effort_value: UNKNOWN` is a
conflict, yields `UNKNOWN`, and retains both facts.

Positive individual testing requires an explicit
`INDIVIDUAL_PATHOGEN_TEST` input scope, source testing ID, exact-source target
and result mappings, and consistent individual counts. The safe
`testing_scope_attestation` carries source/product/version, canonical target
and result IDs, rule references, eligibility, and a stable SHA-256 reference
over the private artifact ID and source testing ID. It never exposes the raw
testing ID. Testing life stage is optional for this construct.

`coverage_identity` hashes scientific context, including normalized canonical
IDs, source vintage, and temporal semantics. It does not include
`evidence_basis`. `result_revision` hashes the safe scientific projection and
the exact evidence basis; `result_id` is `coverage-result:v2:<revision>`.
Identical replay is idempotent. Different synthetic and source-backed
realizations of the same context have distinct immutable IDs. Neither changes
historical v1 rows.

An unresolved source county row may be linked to an `UNKNOWN` result using
`surveillance-source-only-county-evidence-v1`. It cannot establish publisher
omission or county completeness. Safe projection excludes artifact URI, raw
source content, credentials, and credential-like path values in allowlisted
fields. Current-code source-backed replay remains `NOT PROVEN`.
