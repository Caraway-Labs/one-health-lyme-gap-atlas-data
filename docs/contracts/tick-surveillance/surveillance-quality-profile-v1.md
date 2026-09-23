# Surveillance-quality profile v1

Status: Implemented for the bounded canonical tick-surveillance scopes below
Owner: Atlas data stewardship and engineering
Quality-method version: `surveillance-quality-profile-v1`
Companion schema: `surveillance-quality-profile-v1.schema.json`

## Purpose and boundary

This additive contract records a transparent, deterministic analytical quality
profile for one canonical tick-surveillance observation. It is deliberately a
profile, not an overall score: it has no numeric values, weights, aggregation,
probability, confidence interval, or disease-risk meaning. `ASSESSED` means
the component's available evidence was evaluated; its reason codes can still
state material limitations. `UNKNOWN` means evidence is unavailable or not
documented. `NOT_APPLICABLE` means the source design does not call for that
component; it is not a favorable result.

The profile extends neither the canonical observation's scientific meaning nor
the governed normalization registry. It references the existing canonical
identity and source/version/record/run/artifact/retrieval/method lineage. It
does not create a second provenance ledger or persistent quality store.

Technical ingestion `QUALITY` verifies source/contract/runtime validity. This
profile records analytical evidence separately. Neither technical validity nor
any component establishes biological absence, county representativeness,
cross-method pooling eligibility, source authorization, public release, human
disease risk, or causal importance.

## Components and applicability

| Component | Applies to | Meaning and deterministic boundary |
| --- | --- | --- |
| `TECHNICAL_SOURCE_VALIDITY` | All | Canonical structural validation; it is not representativeness or scientific confidence. |
| `PROVENANCE_COMPLETENESS` | All | Existing canonical source/version/record/run/artifact/retrieval/method references are all present. |
| `EFFORT_DENOMINATOR_COMPLETENESS` | `COLLECTION_ABUNDANCE`, `PATHOGEN_TESTING` | Assesses documented collection effort only. County status is `NOT_APPLICABLE`; zero ticks with documented effort remains valid evidence. |
| `METHOD_DOCUMENTATION` | All | Assesses whether the canonical observation retains a collection/testing method, not whether methods are comparable. |
| `SPATIAL_REPRESENTATIVENESS` | All | County status is county-native. Site/event observations retain `NOT_COUNTY_REPRESENTATIVE`, mapping state, and partial/unmapped/ambiguous evidence. |
| `TEMPORAL_COVERAGE_CONTINUITY` | All | Distinguishes cumulative status from retained point/period time. It does not infer unrecorded continuity. |
| `TAXONOMIC_LIFE_STAGE_RESOLUTION` | All | Retains documented versus unresolved life-stage detail without ranking biological importance. |
| `PATHOGEN_TESTING_DENOMINATOR_VALIDITY` | `PATHOGEN_TESTING` | Assesses a present positive individual-test denominator. Other types are `NOT_APPLICABLE`. It does not make pooled testing individual evidence. |
| `COMPARABILITY_ELIGIBILITY` | All | Always records `METHOD_COMPARABILITY_NOT_ESTABLISHED` until a separate reviewed methodology approves a rule. Vocabulary normalization never supplies that rule. |
| `FRESHNESS_REVISION_STATE` | All | Retains source version/retrieval evidence and a source-provided stale/revision-sensitive flag when present. It has no universal age threshold. |
| `KNOWN_SOURCE_LIMITATIONS` | All | Carries source-design limitations that are explicit in the reviewed canonical source scope; otherwise the component is `UNKNOWN`. |

## Reason-code inventory

Reason codes are machine-readable members of this versioned method. They are
evidence descriptions, not ordinal grades. The evaluator emits only these
codes: `CANONICAL_RECORD_STRUCTURALLY_VALID`, `CANONICAL_LINEAGE_RETAINED`,
`PROVENANCE_INCOMPLETE`, `STATUS_DESIGN_NO_ACTIVE_EFFORT`,
`EFFORT_DOCUMENTED`, `VALID_ZERO_WITH_DOCUMENTED_EFFORT`, `EFFORT_UNKNOWN`,
`EFFORT_UNAVAILABLE`, `SAMPLING_IMPRACTICAL`, `METHOD_DOCUMENTED`,
`METHOD_NOT_REPORTED`, `COUNTY_NATIVE_STATUS`,
`SITE_EVENT_NOT_COUNTY_REPRESENTATIVE`, `PARTIAL_SPATIAL_COVERAGE`,
`UNMAPPED_SITE_GEOGRAPHY`, `AMBIGUOUS_SITE_GEOGRAPHY`,
`REPRESENTATIVENESS_UNKNOWN`, `CUMULATIVE_STATUS_ONLY`,
`OBSERVATION_TIME_RETAINED`, `TEMPORAL_COVERAGE_UNKNOWN`,
`TAXON_LIFE_STAGE_DOCUMENTED`, `LIFE_STAGE_NOT_RESOLVED`,
`NOT_A_PATHOGEN_TESTING_OBSERVATION`, `INDIVIDUAL_TEST_DENOMINATOR_VALID`,
`TEST_DENOMINATOR_UNAVAILABLE`, `NON_RANDOM_PATHOGEN_TEST_SELECTION`,
`METHOD_COMPARABILITY_NOT_ESTABLISHED`, `SOURCE_VERSION_AND_RETRIEVAL_RETAINED`,
`STALE_OR_REVISION_SENSITIVE`, `SOURCE_LIMITATION_RETAINED`,
`VARIABLE_SAMPLING_INTENSITY`, `STATUS_SOURCE_LIMITATION_RETAINED`,
`REPORTED_NO_RECORDS_NOT_BIOLOGICAL_ABSENCE`, and
`SOURCE_LIMITATIONS_NOT_DOCUMENTED`.

`STALE_OR_REVISION_SENSITIVE` is emitted only when the existing canonical
`quality_flags` retains that source-specific signal; no date arithmetic or
freshness threshold is invented. The approved NEON RELEASE-2026 mappings emit
their documented site/event, variable-intensity, and non-random-test-selection
limitations. No other source gets those source-specific codes by inference.

## Consumer interpretation

Consumers must show every component and reason code with this profile's
version, and retain its canonical provenance references. They must make an
`UNKNOWN` visible rather than treating it as low quality, neutral quality, a
zero, or biological absence. `NOT_APPLICABLE` must not be displayed as a pass.

Quality evidence and representativeness are separate: a technically valid NEON
site/event observation remains non-county-representative. Quality evidence and
sampling uncertainty are separate from harmonization, transformation, and model
uncertainty; this profile does not calibrate any of them. A documented method
does not authorize pooling, and no component makes a surveillance observation a
disease-risk conclusion.

## Bounded source-backed evidence

The source-specific rules in this version use the retained, governed DEV
evidence from #162: NSF NEON `DP1.10093.001` and `DP1.10092.001`, frozen
`RELEASE-2026`, `BLAN` / `2016-05`, run
`ea8db548-62b0-4632-84ca-02eee97ead41`. The run recorded 31 immutable
package-member artifacts, 171 canonical records, and `STAGED` Tier-B state.
No acquisition is repeated here, and no artifact URI, signed URL, raw payload,
or restricted CDC content is part of this contract. Independent fixtures are
synthetic and are not presented as governed DEV observations.

## Explicit deferrals

This contract does not define source equivalence, method comparability,
county/site aggregation, fresh-enough thresholds, calibrated uncertainty,
derived-metric propagation, broad semantic lineage, a persistent quality
database, or an aggregate quality score. Those decisions remain with the
reviewed methodology and the explicitly separate #166, #191, and #193 scopes.
