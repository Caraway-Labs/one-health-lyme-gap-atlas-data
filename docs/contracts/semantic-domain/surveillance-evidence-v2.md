# DATA429 source-supported evidence interpretation v2

Baseline: main `819dde4974d4bd0c6acc3235dfaeeb146098233a`, 2026-10-06.
Status: implementation candidate; no production/public activation or live
acceptance claimed. The merged PR562 v1 fixture remains unchanged.

`surveillance_evidence_mapping.map_surveillance_evidence` composes the existing
#188 mapper. It validates exact source/version/run/artifact/record, canonical
scope, normalized strata, quality references and metadata first; it then adds
a revision-bound interpretation to that same mapped result. No second
observation store, classifier service, ingestion or public endpoint is added.

## Vocabulary and exact current eligibility

Version `atlas-surveillance-evidence-v2` uses the five current #429 tokens:
`established`, `detected_below_establishment`, `sampled_not_detected`,
`no_qualifying_record`, `unknown`. V1's longer detection token is preserved in
the historical fixture contract; it is not silently renamed.

| Existing governed mapping | Required evidence | State |
| --- | --- | --- |
| CDC `county_tick_status`, definition 1, 2025, county/cumulative, `scapularis_status` | Exact publisher value `Established` | `established` |
| Same tick mapping or CDC `county_pathogen_status`, definition 1, 2025, county/cumulative, `burgdorferi_status` | Exact publisher value `No records` | `no_qualifying_record` |
| NEON `neon_pathogen_test`, definition 1, `DP1.10092.001`, RELEASE-2026, BLAN/2016-05, site/event | Canonical individual tested count 1, positive count 0, explicit test/sample identity, empty canonical quality flags, and exactly one retained negative-result proof matching the existing normalization registry | `sampled_not_detected` for that source test only |
| `Reported`, pathogen `Present`, positive site test, collection count, missing/incomplete proof, unresolved or other source mapping | Existing source meaning retained; stronger evidence-state relationship unsupported | `unknown` with reason code |

CDC rules require the source cumulative endpoint 2025-12-31. Other dates abstain.
No numeric establishment threshold is calculated. No county omission creates a
record. A generic zero cannot satisfy sampling evidence. Missing quality flags
are unknown, not equivalent to an empty validated list. Any nonempty quality
context abstains conservatively until a reviewed eligibility refinement exists;
this does not replace #157 quality or declare that every flagged test is invalid.
The NEON negative rule reuses frozen individual-test normalization and retained
source identities; it does not invent collection effort or imply county absence.

The current contracts call CDC `Reported` a publisher cumulative reported
classification. They do not establish its precise relation to establishment
criteria for the selected source version. The CDC pathogen contract describes
detection without an establishment criterion. Consequently neither is assigned
`detected_below_establishment`. A human source-rule decision is needed to make
that fifth vocabulary state assignable on current governed sources. It is not
substituted for generic detection. This is the remaining scientific decision,
not permission to fabricate an establishment threshold.

## Compatibility, evidence revisions and consumers

The returned existing observation, lineage, value state, metadata, unit,
denominator and IDs are byte-for-byte unchanged. The interpretation retains
their observation/revision and lineage IDs and digests the complete canonical
evidence so changes to test/method/quality proof create another evidence revision
even when legacy semantic value identity is unchanged. Source values and private
proofs are never rewritten. Stale dates remain dates; no freshness threshold,
current-status extension, pooling or temporal inference is introduced.

`project_surveillance_evidence` recomputes the interpretation from validated
inputs and passes the semantic payload through existing consumer gates. Its
companion exposes state/reasons, explicit evidence tier, rule version, bound
semantic IDs, unchanged value state, limitations and evidence revision only.
Private canonical proof, raw fields and its internal digest are excluded.
Fixture mode requires a literal boolean and synthetic source-version IDs.
Only synthetic consumer-safe metadata can simulate admitted fixture lineage.
Real tick mappings retain internal lineage visibility and public admission
fails under the existing consumer gate. No production hook is installed.

## Scientific and acceptance limits

Source rules reuse [canonical tick v1.2](../tick-surveillance/canonical-tick-surveillance-v1.md),
the [approved normalization registry](../tick-surveillance/tick-surveillance-normalization-v1.json),
CDC source definition files, and [existing semantic mappings](atlas-semantic-source-mappings-v1.md).
The [CDC establishment explanation](https://www.cdc.gov/ticks/data-research/facts-stats/blacklegged-tick-surveillance.html)
was checked 2026-10-06 and remains source-specific; it does not prove absence in
other counties. No restricted workbook is downloaded by this change.

The five current ACs have: versioned vocabulary plus bounded rules; tested
canonical→semantic→fixture-consumer propagation; unchanged #188 observations;
unsupported→unknown behavior; no UI/new ingestion. Source-backed governed
replay and production/public admission are **not proven**. The full story stays
open until parent scientific/product acceptance decides the unresolved detection
rule and verifies required live evidence. Closed #430/#431 are not approval.
