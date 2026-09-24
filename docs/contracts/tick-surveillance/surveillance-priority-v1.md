# Surveillance investigation triage v1

Status: Approved for bounded internal Story #172 implementation by the product/data steward; no public or PROD release
Owner: Atlas data stewardship and engineering
Methodology: `surveillance-priority-v1`
Inputs: `surveillance-coverage-v1`, `surveillance-coverage-result-v1`, `surveillance-quality-profile-v1`, `surveillance-quality-propagation-v1`

## Operational decision

For one comparable evidence unit, determine the **kind of surveillance-data review or follow-up** supported by its #171 categorical coverage state. This method is an unordered triage classification. It does not decide which item is more urgent, allocate funds, predict disease, estimate Lyme risk, prove underreporting, establish biological presence or absence, or grade an agency. It is distinct from the existing Atlas county priority score and must never be substituted into that score or its public release.

## Exact input and comparison cohort

The input is one serialized, consumer-safe `surveillance-coverage-result-v1` result with its exact result ID/revision, method/calculation versions, source scope, evidence basis, reasons, quality, representativeness, and safe lineage. Source-backed evidence may be labeled `CURRENT_CODE_SOURCE_BACKED_REPLAY` only after independent current-code replay proof. Historical #162 ingestion and synthetic fixtures/DEV persistence do not establish such proof.

Each cohort fixes one construct, source family/product, exact dataset, source version and vintage, native grain, and time semantics. County cohorts additionally fix publisher scope version, canonical eligible universe version, cumulative-through date, and the reported vector taxon or pathogen target; vector and pathogen status stay separate. Site/event collection cohorts fix source event date, collection method, tick species, and life stage; effort cohorts also fix effort unit. Required context must be resolved and comparable: missing, `UNKNOWN`, `UNRESOLVED`, `AMBIGUOUS`, `UNSUPPORTED`, `NOT_REPORTED`, `NOT_APPLICABLE`, or aggregate/`MIXED` collection strata do not form a cohort. A collection method must be one of the approved resolved canonical method labels in the pinned normalization registry; unresolved method text may remain in the #171 result but is not a comparable method. Individual testing cohorts fix tested date, pathogen target, and the approved individual pathogen testing scope. Testing life stage is not required. Fields legitimately inapplicable to a construct are explicitly `NOT_APPLICABLE` in cohort identity. The cohort ID is a hash of that exact context. Missing or ambiguous required context yields `NOT_DEFENSIBLE`, not an inferred cohort. An `UNKNOWN` result with absent event identity remains `EVIDENCE_VERIFICATION` with no cohort or tie group: the verification action is explicit, but no comparison is defensible.

No cohort compares county status to NEON SITE_EVENT observations, one construct to another, vector to pathogen status, or drag to flag collection methods. A mapped NEON site is navigation context only and remains `NOT_COUNTY_REPRESENTATIVE`; unmapped/ambiguous sites keep native identity without a county assignment. Cumulative status is not an annual sampling claim, and an event is not site-period completeness. No county percentage, expected-event denominator, method/source normalization, or combined list is approved.

## State-to-disposition matrix

Dispositions are **not ordered**. `EVIDENCE_GAP_FOLLOW_UP` identifies a specific documentation/observation gap for follow-up; it is not a severity grade. Underlying states and reason codes remain distinct even when they share a disposition.

| Construct | #171 states | v1 disposition |
| --- | --- | --- |
| County status representation | `REPORTED_STATUS` | `NO_CURRENT_GAP_SIGNAL` |
| County status representation | `PUBLISHER_NO_RECORDS` | `EXPLANATORY_LIMITATION` |
| County status representation | `NOT_REPORTED_IN_DATASET` | `EVIDENCE_GAP_FOLLOW_UP` only with #171 complete scoped snapshot proof |
| County status representation | `UNKNOWN` | `EVIDENCE_VERIFICATION` |
| County status representation | `UNAVAILABLE` / `NOT_APPLICABLE` | `UNAVAILABLE` / `NOT_DEFENSIBLE` |
| Site/event sampling | `SAMPLED_EVENT` | `NO_CURRENT_GAP_SIGNAL`, including valid sampled zero |
| Site/event sampling | `SAMPLING_IMPRACTICAL` | `EXPLANATORY_LIMITATION` |
| Site/event sampling | `UNKNOWN` | `EVIDENCE_VERIFICATION` |
| Site/event sampling | `UNAVAILABLE` / `NOT_APPLICABLE` | `UNAVAILABLE` / `NOT_DEFENSIBLE` |
| Effort documentation | `DOCUMENTED_POSITIVE_EFFORT` | `NO_CURRENT_GAP_SIGNAL` |
| Effort documentation | `MISSING_EFFORT` / `ZERO_EFFORT` | `EVIDENCE_GAP_FOLLOW_UP`, with distinct retained state/reason |
| Effort documentation | `SAMPLING_IMPRACTICAL` | `EXPLANATORY_LIMITATION` |
| Effort documentation | `UNKNOWN` / `UNAVAILABLE` | `EVIDENCE_VERIFICATION` / `UNAVAILABLE` |
| Testing denominator | `DOCUMENTED_POSITIVE_TEST_DENOMINATOR` | `NO_CURRENT_GAP_SIGNAL`, including zero positive tests |
| Testing denominator | `MISSING_TEST_DENOMINATOR` / `ZERO_TEST_DENOMINATOR` | `EVIDENCE_GAP_FOLLOW_UP`, with distinct retained state/reason |
| Testing denominator | `UNKNOWN` / `UNAVAILABLE` / `NOT_APPLICABLE` | `EVIDENCE_VERIFICATION` / `UNAVAILABLE` / `NOT_DEFENSIBLE` |

`NOT_REPORTED_IN_DATASET` is valid only when the underlying #171 result records matching approved complete publisher snapshot and universe evidence; absent rows alone stay `UNKNOWN`. `PUBLISHER_NO_RECORDS` does not mean biological absence or have precedence over reported status. `SAMPLING_IMPRACTICAL` is not failed or zero sampling. `UNKNOWN` prompts evidence verification, not automatic highest priority. Missing and zero effort/testing denominators remain separate states. M1/M2 and disease positivity are not inputs.

## Quality, freshness, ties and sensitivity

#165 components, #166 propagated reasons/limitations, source/version lineage, and `STALE_OR_REVISION_SENSITIVE` are copied into the safe result to explain it. They do not silently change disposition. No numeric quality score, weight, freshness cutoff, or priority magnitude exists. Unresolved source revisions remain #171 `UNKNOWN` and route to verification; a new source revision produces a distinct coverage and priority result revision.

Equal dispositions within the same exact cohort share a deterministic tie-group ID. Lexical result-ID ordering is a display convenience only. There is no ordinal position, scientific rank, precedence among labels, or hidden tie-break. `UNAVAILABLE` and `NOT_DEFENSIBLE` receive no tie group or false rank. A mixed-cohort sort is rejected; downstream screens must use separate prominently labeled sections.

Sensitivity is categorical: changing optional evidence, the #171 state, approved completeness proof, revision, missingness, or a comparability limitation may change disposition or eligibility. Compare explicit before/after output states and reasons; no numeric sensitivity range exists.

## Usefulness and bias review

Before operational or public use, review representative source-backed results and who would act on each label. Sparse reporting may appear artificially important; rich metadata may appear artificially complete. Missing data is not disease burden or agency failure. Publisher `NO_RECORDS` is not biological absence. Impractical sampling is not a failed collection. Site evidence cannot be generalized to counties. Triage labels must not be presented as the existing Atlas county score or as public-health urgency. These examples are synthetic until current-code source-backed replay is independently proven.

## Deferrals

No ordered tiers, points, numeric score, weight, normalized value, source equivalence, freshness threshold, cross-construct/county-site comparison, combined priority list, automatic allocation, generalized #188 ontology, API/web view, PROD publication, or public release. Any new interpretation requires a separate recorded steward decision.
