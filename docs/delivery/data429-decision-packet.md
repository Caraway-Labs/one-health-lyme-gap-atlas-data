# DATA429 bounded implementation and decision packet

## Delegated Reported interpretation decision - 2026-10-06

Recorded before candidate code changes, from main
`b36893cf4f77a98e4363ea77f0267c36596c8933` (PR615 after merged PR614).
Under Matthew's explicit overnight
delegation, the coordinating agent selected this bounded implementation meaning:
**Detected; establishment criteria not documented as met in the source.**
This is a delegated implementation decision backed by independently researched
official evidence, not a claim that Matthew personally performed scientific
review or that formal contract-steward approval occurred.

The candidate applies only to the original `Reported` value in existing
`county_tick_status` / `scapularis_status` (*Ixodes scapularis*), source
`cdc-ixodes-county-status-2025`, definition 1, vintage 2025, county/cumulative
endpoint 2025-12-31. The pinned workbook is
`Public_Use_Ixodes_County_Table_2026_03252026.xlsx`, sheet `Ixodes records 2025`,
SHA-256 `e35a5066a7c77b2e79c50f315a18e042405ab7baa8a414a1a907792bb25d2adc`.
The existing canonical/semantic mapper remains authoritative for exact input
identity and lineage; the interpretation preserves its value and provenance.

[CDC's dataset page](https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html)
links the through-2025 workbook and defines cumulative publisher categories.
[Eisen et al. 2016, page 2](https://stacks.cdc.gov/view/cdc/39097/cdc_39097_DS1.pdf)
also includes historical Reported records with unspecified tick counts or life
stages. The interpretation therefore preserves the publisher label without
calculating a threshold. Count, life stage, collection date and effort stay
missing; it implies neither current ecological non-establishment nor a 2025
collection event or sampling completeness. Pathogen Present and other taxa
remain unchanged.

Governance boundary: canonical tick v1.2 explicitly records formal
contract-steward approval as pending. Existing live mapping requires REVIEWED
semantic metadata and consumer publication requires its separate admission gate.
This candidate neither supplies nor changes those review/admission records.
Independent code review is required before merge; governed source-backed
canonical replay remains unproven without genuine metadata/authority inputs.
The earlier sections below are historical, including PR614's abstention rule.

## Lane A continuation - 2026-10-06

Current issue text and main `819dde4974d4bd0c6acc3235dfaeeb146098233a`
were reconciled before editing. PR562 remains the historical synthetic scaffold.
Branch `codex/data429-source-evidence` reuses the isolated task-5 worktree.
No open DATA429 PR was found at dispatch. No shared mapper/consumer file,
migration, source config, Web/ML/API implementation or other DATA lane is changed.

The v2 continuation composes the existing source mapper and consumer gates.
It classifies only publisher Established / explicit No records, and a
source-normalized individual NEON negative test with complete sample/test/quality
proof in the frozen BLAN/2016-05 scope. It preserves all legacy semantic objects.
See [v2 contract and eligibility matrix](../contracts/semantic-domain/surveillance-evidence-v2.md).

Current five-criterion mapping:

| Acceptance criterion | Evidence / limitation |
| --- | --- |
| Versioned vocabulary and source rules | v2 uses current issue tokens; exact CDC/NEON rules; unsupported detection/establishment relation abstains. |
| Canonical→semantic→consumer preservation | Wrapper reuses canonical source output, existing semantic mapper and fixture-safe consumer projection; no live/public admission claim. |
| #188 compatibility | Tests compare every legacy mapped field unchanged, retaining value states, quality and immutable lineage. |
| Unsupported→unknown | Missing sampling/QA/result proofs, unsupported source tuples and non-establishment detections abstain; invalid lineage still fails closed. |
| No UI/new-source ingestion | Three bounded implementation/test/contract files plus this packet; no source activation or migration. |

**Remaining decisions/evidence:** The existing CDC contract's `Reported` label
does not prove its relation to establishment criteria, and pathogen `Present`
has no establishment criterion. Do not assign `detected_below_establishment`
until a reviewed exact-source rule provides that evidence. The current rule
does not assert that flagged tests are scientifically invalid; all nonempty or
missing quality context abstains pending an exact-source eligibility refinement.
Governed source-backed replay, formal scientific/product acceptance and public
admission remain unproven. No new reads of restricted source artifacts, paid
execution, grants or source acquisition are proposed here.

The story remains open. Peer review and acceptance belong to the parent;
implementation readiness and closed #430/#431 are not scientific approval.
The original packet below remains historical evidence, not the current AC list.

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
