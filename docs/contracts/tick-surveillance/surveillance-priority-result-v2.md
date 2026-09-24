# Surveillance priority safe result v2

Status: Internal DEV remediation candidate for Story #172
Owner: Atlas data stewardship and engineering
Schema: `surveillance-priority-result-v2.schema.json`
Methodology: `surveillance-priority-v1`

#172 consumes only `surveillance-coverage-result-v2`. It uses the exact #171
source vintage tuple and safe scientific attestations. Cohort and tie-group
keys use canonical IDs, never display labels. Collection cohorts require
attested taxon, life stage, collection method, and effort unit. Testing cohorts
require attested pathogen/result mappings and a valid #171
individual-testing-scope attestation. County cohorts require an attested
nonaggregate dimension, resolved canonical FIPS, complete scoped snapshot,
and cumulative time. Source-only county evidence is always incomparable.

Missing, foreign, ambiguous, unsupported, aggregate, conflicting, unresolved,
period-incompatible, or vintage-ineligible context yields no cohort or tie
group. The safe #171 evidence and deterministic #172 result remain available
with `COMPARISON_COHORT_UNPROVEN`. The disposition follows the v1 unordered
triage semantics (`NOT_DEFENSIBLE`, `EVIDENCE_VERIFICATION`, or `UNAVAILABLE` as
appropriate). There is no rank, score, or resource-allocation order.

The result includes exact #171 `evidence_basis` and revision. Its v2 immutable
revision/ID therefore distinguish synthetic and source-backed realizations.
V102 and historical priority rows remain untouched. Current-code source-backed
replay remains `NOT PROVEN`; this contract makes no public or PROD claim.
