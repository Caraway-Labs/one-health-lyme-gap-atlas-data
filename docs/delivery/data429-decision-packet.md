# DATA429 bounded implementation and decision packet

Status: draft implementation; **do not close #429 or activate production**.
Base audited: `c5a23105719ac77f8abbca9b613b661654e22845`.
Branch: `codex/data429-evidence-contract`.

## Decisions requiring human scientific/steward review

1. Approve or amend the proposed vocabulary, especially the applicability of
   `detected_below_establishment_criteria` to pathogen evidence. CDC pathogen
   detection is not, by itself, evidence of a defined establishment threshold.
2. Supply a versioned exact-source rule matrix: publisher/product, frozen source
   definition/version/vintage, allowed native grain, species/pathogen/strata,
   temporal scope, source-native evidence and disqualifying quality conditions.
   Identify the reviewer and recorded decision; do not use a caller boolean as
   scientific approval.
3. Decide eligible CDC county-status mappings for explicit labels only. Review
   `Reported` and `No records` against retained publisher definitions; do not
   infer sampled-negative from either label or an absent county row.
4. Specify qualifying NEON collection/testing evidence using the frozen
   RELEASE-2026 dictionaries, completed effort, impractical-sampling/QA flags,
   individual-test scope and exact sample/test identity. Decide whether any
   current scope can carry sampled-negative. No new denominator is proposed.
5. Approve consumer admission/versioning and the persistence/revision binding
   before attaching the envelope to live canonical/semantic outputs. API #88
   owns public propagation. No global stale-data cutoff, passive/systematic
   equivalence or inferred geography/identification confidence is proposed.

These decisions are required by #429's human-review and ambiguity policy, not
an additional agent approval process. The implementation makes them concrete
without claiming approval or introducing a production classifier.

## Acceptance mapping

| #429 criterion | Delivered evidence / remaining dependency |
| --- | --- |
| Versioned vocabulary | Proposed v1 docs and executable `STATES`; approval pending. |
| Sampled-negative requires qualifying sampling | Synthetic boundary requires both proofs and reference; real eligibility rule pending. |
| No qualifying record is not absence | Separate state, unchanged literal/value state, limitations and regression fixture. |
| Unknown fallback | Absent/incomplete/ambiguous fixture assertions abstain; real source mapping pending. |
| Source-aware establishment/detection | Required source-definition/criteria references, no inferred thresholds; rule matrix pending. |
| County versus site/event | Existing domain validator and immutable scope retained; no aggregation. |
| #188 compatibility | Existing contracts, IDs, value states, lineage and consumer v1 unchanged; focused regressions. |
| All states/ambiguous/stale/mixed/revised | Synthetic tests; mixed/revised source assertions cannot bind to another observation revision. No pooling. |
| Consumer-safe projection | Fixture-only allowlisted companion; scientific/API/public admission pending. |

## Release requirements

No migration, backfill, source acquisition, grant or deployment is required for
this fixture-only module. No DEV/PROD or live-consumer evidence is claimed.
Parent coordinates independent code review, refreshed-main exact Quality CI,
serialized merge/release. Scientific review must precede any live classification
or public semantic activation. Reverting this commit changes no stored rows.

Validation results and exact final head are recorded in the PR/handoff.
