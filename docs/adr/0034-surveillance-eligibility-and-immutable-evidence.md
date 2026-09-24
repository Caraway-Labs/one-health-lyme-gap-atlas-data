# 0034: Source-specific surveillance eligibility and immutable evidence

Status: Proposed for protected review
Date: 2026-09-24
Decision owner: Atlas product/data stewardship and engineering

## Context

The consolidated Epic #159 audit at `b59a934` found twelve defects
(`AUDIT-159-001` through `AUDIT-159-012`). Global canonical membership and
display labels could be mistaken for exact-source eligibility. #171 omitted
scientific and testing-scope proof from its safe result, so #172 reconstructed
cohorts from free text. Evidence basis, mapping proof, and temporal semantics
were not fully represented in immutable identities. The existing V101/V102
rows and migrations must remain immutable.

## Decision

The five decisions approved for the consolidated remediation are:

1. Accept a governed canonical ID or label only with an approved exact-source
   mapping for publisher, product, version, field, and role. Normalize to the
   canonical ID for scientific identity and comparisons. Keep labels for safe
   display; conflicting ID/label proof fails closed.
2. Retain unresolved county source rows in a separate, safe, versioned
   source-only evidence envelope. Do not weaken the canonical county FIPS
   requirement or turn source-only evidence into county coverage or omission.
3. Carry a versioned individual-testing attestation from #171 to #172. It
   binds source/product/version, explicit scope, safe testing identity,
   pathogen/result canonical IDs, mapping rules, and eligibility. Testing
   life stage remains optional for denominator availability.
4. Keep `coverage_identity` as scientific context. Include `evidence_basis`
   in the immutable #171 result revision/ID and propagate it into the #172
   result revision/ID. Synthetic and source-backed instances may coexist.
5. Require an approved publisher/source/version/vintage/construct tuple for
   positive #171 states and #172 cohorts. No free-text vintage inference.

`surveillance-scientific-eligibility-v1.json` records the bounded approved
tuples. The normalization registry remains the authority for exact lexical
mapping. `surveillance-coverage-result-v2` and
`surveillance-priority-result-v2` carry the safe proof and distinct immutable
identities. Existing v1 results and V101/V102 migration history are retained.

## Consequences

Unproven scientific dimensions, foreign mappings, aggregate values, unknown
vintage, period-valued collection evidence, and unresolved testing scope can
produce safe fail-closed results with no comparison cohort or tie group.
Positive effort contradicting `missingness: UNKNOWN` is `UNKNOWN`, with both
facts retained. A source-only county row has no canonical county FIPS.

No numerical score, cross-source normalization, county active-surveillance
aggregation, public API, web view, PROD publication, source reacquisition, or
source-backed replay is authorized by this decision.

## Acceptance criteria

- Registry-generated tests exercise all relevant canonical values and mapping
  rules through both safe serializers, with zero invalid positive states and
  zero invalid cohorts.
- Safe output rejects credential-like paths in allowlisted values.
- Exact-source scientific and temporal evidence changes alter the appropriate
  immutable result identity or revision; identical replay is idempotent.
- Bounded exact-main DEV verification includes each root-cause class and safe
  read-back without rewriting historical rows.

## Rollout and rollback

Protected Quality and DEV verification precede merge acceptance. v2 results
append to the existing DEV-only stores. Rollback stops new v2 writes and leaves
v1 and v2 history intact. The current-code source-backed replay remains
`NOT PROVEN`.

## Links

- `docs/contracts/tick-surveillance/surveillance-coverage-v1.md`
- `docs/contracts/tick-surveillance/surveillance-priority-v1.md`
- `docs/contracts/tick-surveillance/surveillance-scientific-eligibility-v1.json`
- `docs/contracts/tick-surveillance/surveillance-coverage-result-v2.md`
- `docs/contracts/tick-surveillance/surveillance-priority-result-v2.md`
