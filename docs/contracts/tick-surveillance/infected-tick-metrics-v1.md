# Initial infected-tick surveillance metrics v1

Status: Implemented methodology contract for Story #167; no calculation or publication is authorized by this document  
Owner: Atlas data stewardship and engineering  
Methodology version: `infected-tick-metrics-v1`

## Purpose and scope

This contract freezes the initial, narrow, source-backed methodology for derived infected-tick surveillance measures. It does not change the canonical observation contract, normalization registry, analytical-quality method, persistence model, API, public release, or calculation work owned by Story #168.

The reviewed source scope is NSF NEON `DP1.10093.001` (collection) and `DP1.10092.001` (pathogen testing), frozen `RELEASE-2026`. The only governed DEV evidence is `BLAN` / `2016-05`, run `ea8db548-62b0-4632-84ca-02eee97ead41`. This scope is neither a floating NEON feed nor evidence about a county, the general tick population, exposure, incidence, or human risk.

The companion machine-readable source matrix is [`infected-tick-metrics-v1-source-eligibility.json`](infected-tick-metrics-v1-source-eligibility.json). It is normative for source-shape eligibility; this document is normative for scientific meaning and unavailable behavior.

## Dispositions

| Candidate family | Disposition | Reason |
| --- | --- | --- |
| Observed pathogen prevalence among eligible tested ticks | **APPROVED** | A proportion is defined only for a single compatible, individual-test stratum with a positive tested denominator. It is observed prevalence in the tested population, not population or county prevalence. |
| Effort-normalized collection density | **APPROVED** | A count divided by documented source-reported collection area is defined only within one compatible collection stratum and method. |
| Combined infected-tick estimator | **DEFERRED** | Current evidence does not establish a collection-to-testing population linkage at species, life-stage, event, method, and testing-selection-design grain. No abundance-times-prevalence or infected-ticks-per-effort calculation is approved. |
| County, cross-site, cross-event, or cross-period metric | **DEFERRED** | No reviewed representativeness or aggregation method supports it. A county relationship never changes a native site/event observation into county evidence. |
| Pooled-test prevalence, confidence interval, hard minimum sample size, or quality-weighted metric | **DEFERRED** | No reviewed methodology exists. Retain numerator and denominator transparently. |

## Shared eligibility and output rules

Every input needs canonical observation, source dataset/version/record, run, immutable artifact, retrieval time, canonical-method version, and pinned exact normalization provenance. Relevant taxonomy, pathogen, result, method, and unit mappings must be `APPROVED`; `UNKNOWN`, `AMBIGUOUS`, and `UNSUPPORTED` mappings are ineligible. `HardTick DNA Quality` and `Ixodes pacificus` supporting assays are provenance only and never pathogen-metric input.

The native output grain is one `SITE_EVENT` stratum. Result identity includes metric ID/version; source/release; site, event, sample/subsample; collection or tested date; taxon; resolved life stage; pathogen (prevalence); collection method (density); testing method/source scope (prevalence); and exact input canonical IDs. No dimension may be dropped. Different species, life stages, pathogens, collection methods, testing designs, events, sites, dates, releases, or source populations are separate results, never pooled.

`UNMAPPED` is an eligible native site/event geography when other requirements hold. Its result retains null county FIPS and `NOT_COUNTY_REPRESENTATIVE`. A mapped site remains `NOT_COUNTY_REPRESENTATIVE`. Partial coverage is a limitation, never a numerical correction. No county output exists in v1.

`UNKNOWN` means a required fact is not evidenced; `UNAVAILABLE` means the metric cannot be calculated under this methodology. A numeric `0` is valid only with a positive denominator and all eligibility rules. Missing evidence is never zero. Every output retains numerator, denominator, unit, state, input IDs, source/version/run/artifact lineage, registry/rule IDs, methodology version, and revision/retrieval provenance.

## M1: observed pathogen prevalence among eligible tested ticks

**Identity.** `OBSERVED_PATHOGEN_PREVALENCE`; derived; methodology version `infected-tick-metrics-v1`; unit `proportion` (dimensionless `[0,1]`). A UI may multiply by 100 for display but must retain the stored proportion.

**Formula.** In exactly one compatible individual-test stratum `s`, `P_s` is eligible canonical `PATHOGEN_TESTING` with the same source scope, taxon, resolved life stage, pathogen, site/event, tested-date, and testing method/source scope whose normalized result is `DETECTED`. `T_s` is the corresponding eligible `DETECTED` or `NOT_DETECTED` individual tests.

`prevalence_s = P_s / T_s`, only if `T_s > 0` and `0 <= P_s <= T_s`.

The NEON row mapping supplies `T_s = 1` per eligible nonblank individual result and `P_s` as 1 or 0. It does not authorize pooled interpretation, collected-tick substitution, or a count from `PATHOGEN_PRESENCE_STATUS`.

**Eligibility.** Require `PATHOGEN_TESTING`, approved pathogen/result mappings, positive integer `ticks_tested`, nonnegative integer `ticks_positive <= ticks_tested`, resolved non-mixed life stage, resolved taxon, retained site/event and tested date, retained testing method/protocol/source scope, and complete lineage. The current NEON canonical `PATHOGEN_TESTING` shape retains the taxon but not resolved `life_stage`; it is therefore `UNAVAILABLE` for M1 until a future canonical input satisfies this already-approved condition. Story #168 must not infer or backfill the stratum.

**Time, geography, boundaries.** `testedDate` is the point-in-time output; `collectDate` is retained lineage. Inputs may combine only with identical complete site/event and tested-date identity: no site-period, seasonal, annual, cross-event, or county aggregation. Zero tested, null/missing tested, positive greater than tested, negative/noninteger counts, blank result, pooled testing, unresolved/mismatched taxon or life stage, pathogen mismatch, testing-method/source mismatch, and event/period mismatch are `UNAVAILABLE`. Zero positive with positive tested is numeric zero, not absence outside tested ticks. A revised source record/release is distinct; no revision selection is approved.

**Interpretation.** Every numeric M1 result states: “Observed prevalence among eligible tested ticks in this source-native stratum; pathogen-test selection is not necessarily random.” Retain non-random selection, variable intensity, comparability, partial coverage, and non-county limitations. Sparse denominators are reported; v1 has no minimum-N threshold and no confidence interval.

## M2: effort-normalized collection density

**Identity.** `EFFORT_NORMALIZED_COLLECTION_DENSITY`; derived; methodology version `infected-tick-metrics-v1`; output unit `ticks_per_square_metre`.

**Formula.** In one compatible collection stratum `c`, `C_c` is source-reported `ticks_collected` and `A_c` is source-reported `collection_effort_value` in square metres from NEON `totalSampledArea`.

`density_c = C_c / A_c`, only if `A_c > 0` and `C_c >= 0`.

`TICKS_PER_SQUARE_METRE -> TICKS_PER_HECTARE` may use the reviewed 10,000 registry factor only after M2 exists with this documented denominator. It is an output-unit conversion, not a way to manufacture density from a count. No other conversion is approved.

**Eligibility.** Require `COLLECTION_ABUNDANCE`, approved taxon/life-stage/method/`SQUARE_METRE` mappings, resolved non-mixed life stage, approved collection method, nonnegative integer `ticks_collected`, finite positive effort, and retained site/event/`collectDate`/lineage. `DRAG_CLOTH` and `FLAG_CLOTH` are distinct, incompatible strata.

**Time, geography, boundaries.** `collectDate` is the point-in-time output. No calendar rollup, cross-event/site aggregation, county projection, or cross-method comparison is approved. Zero collected with positive documented effort is numeric zero. Null/`UNKNOWN`/nonfinite effort, zero effort, missing unit, unsupported conversion, `samplingImpractical`, unresolved taxon/life stage/method, incompatible method, or event/period mismatch is `UNAVAILABLE`; a collection count alone never creates density.

## Quality and limitation integration

`surveillance-quality-profile-v1` is retained for every input and `surveillance-quality-propagation-v1` is required for a derived envelope. Quality is neither a metric weight nor an automatic source-selection rule.

Eligibility-critical quality evidence is structural/provenance support plus the metric-specific denominator/method facts: require `TECHNICAL_SOURCE_VALIDITY` `ASSESSED`, `PROVENANCE_COMPLETENESS` `ASSESSED` with `CANONICAL_LINEAGE_RETAINED`, M2 `EFFORT_DENOMINATOR_COMPLETENESS` `ASSESSED` with `EFFORT_DOCUMENTED`, and M1 `PATHOGEN_TESTING_DENOMINATOR_VALIDITY` `ASSESSED` with `INDIVIDUAL_TEST_DENOMINATOR_VALID`. M2 also requires `METHOD_DOCUMENTATION` `ASSESSED` with `METHOD_DOCUMENTED`; M1 retains testing-method/source scope. These are evidence gates, not scores.

Other components, including `UNKNOWN`, propagate as limitations unless they are the missing eligibility fact. `NOT_APPLICABLE` is neither failure nor favorable quality. Preserve `METHOD_COMPARABILITY_NOT_ESTABLISHED`, `NON_RANDOM_PATHOGEN_TEST_SELECTION`, `PARTIAL_SPATIAL_COVERAGE`, `UNMAPPED_SITE_GEOGRAPHY`, `SITE_EVENT_NOT_COUNTY_REPRESENTATIVE`, `SAMPLING_IMPRACTICAL`, effort/test-denominator reasons, and `STALE_OR_REVISION_SENSITIVE`. An unavailable reason adds to inherited evidence and never replaces it.

## Evidence and #168 handoff

The frozen NEON source-to-canonical field matrix is the source documentation for native grain, fields, individual testing, and exact mapping. The canonical contract and #383 qualification are the product/steward decisions for scope, no pooling, and site/event-not-county interpretation. #165/#166 are engineering constraints that preserve analytical evidence but establish neither comparability nor a metric. No external interval literature was needed because v1 intentionally publishes no interval.

Story #168 may implement only M1 and M2 at this native grain, with these formulas, gates, units, unavailable states, lineage, and propagated metadata. It must not implement a combined estimator, county aggregation, cross-stratum pooling, confidence interval, minimum-N cutoff, quality weighting, persistence/API contract, or canonical-field change.
