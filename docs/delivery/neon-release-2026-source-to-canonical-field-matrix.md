# NEON RELEASE-2026 source-to-canonical field matrix

This matrix documents the implementation delivered by Story #162. It is
limited to NSF NEON `DP1.10093.001` and `DP1.10092.001`, frozen
`RELEASE-2026`, at `BLAN` / `2016-05`; it describes the governed-DEV run, not
a floating NEON feed, a county product, or a public/production release.

The canonical adapter pins normalization registry
`tick-surveillance-normalization-v1` at version `1.0.4` and uses
`tick-surveillance-v1.2`. Every source alias is exact and source-context
specific. Unknown, ambiguous, or unsupported values fail closed rather than
being guessed. Equality of a normalized label does not establish scientific
comparability or permission to pool observations.

## Native joins and grain

| Native table | Native grain and required relationship | Canonical result | Prohibition |
| --- | --- | --- | --- |
| `tck_fielddata` | plot collection event: `siteID` × `plotID` × `eventID`, with `sampleID` when present | collection context shared by site/event records | A zero-tick completed event is not a missing event; an impractical event is not a zero. |
| `tck_taxonomyProcessed` | collection result: `sampleID` → `subsampleID` × taxon × life stage | one `COLLECTION_ABUNDANCE` record | A collection count is never a testing denominator. |
| `tck_pathogen` | individual test: `subsampleID` → `testingID` × `testPathogenName` | one eligible `PATHOGEN_TESTING` record | A blank test result is a blocking failure, not negative. |
| `tck_pathogenqa` | QA rows grouped by `batchID`, identified by `uid` | retained supporting provenance only | `batchID` is not a one-to-one canonical join and must not multiply test records. |

The source-record identity is constructed from frozen release, product,
event/sample/subsample/testing identifiers, and pathogen target where
applicable. Canonical identity additionally carries site/event/sample/subsample/
testing dimensions and source-native strata. The adapter validates unique
`sampleID`, `subsampleID`, and QA `uid`; broken or duplicate native joins block
normalization.

## Field-level mapping

| Source field(s) | Canonical field/behavior | Value kind and denominator | Lineage and limitation |
| --- | --- | --- | --- |
| `tck_fielddata.siteID`, `plotID` | `sampling_site.source_site_id`, `source_plot_id`; `source_geography.source_location_id` | source-reported identifier | Native PLOT identity is retained separately from county identity. |
| `eventID`, `sampleID`, `subsampleID`, `testingID`, `batchID` | `sampling_event` and deterministic canonical/source-record identity | source-reported identifier | `batchID` supports provenance grouping only; it does not create a QA join. |
| `decimalLatitude`, `decimalLongitude`, `coordinateUncertainty` | `source_geography` as EPSG:4326 PLOT coordinates/uncertainty | source-reported geography | `county_relationship` is `UNMAPPED`, null county FIPS, and `NOT_COUNTY_REPRESENTATIVE`; no county aggregate is implemented. |
| `collectDate` | collection `surveillance_period_start` and `_end` | source-reported point-in-time collection date | It is not an inferred period end or annual/cumulative status. |
| `testedDate` | testing `surveillance_period_start` and `_end` | source-reported point-in-time test date | Testing time is distinct from collection time. |
| `samplingMethod` | `collection_method` plus normalization envelope | harmonized only via exact registry rule | `DRAG_CLOTH` and `FLAG_CLOTH` remain distinct; no pooling/comparability rule is implied. |
| `totalSampledArea` | `collection_effort_value` with source-reported `square metre` unit | reported effort when present | The adapter does not derive normalized abundance. A conversion needs a documented denominator and approved registry rule. |
| `samplingImpractical`, `dataQF` | provenance-bearing `quality_flags` | source-reported value mapped by exact registry rule | Impractical/missing effort remains distinct from numeric zero; quality flags are not calibrated uncertainty. |
| `scientificName`, `sexOrAge` | `tick_species`, `life_stage`, normalization envelope | harmonized exact value; native value retained in the envelope | Unrecognized casing/aliases are not silently normalized. |
| `individualCount` in `tck_taxonomyProcessed` | `ticks_collected` for `COLLECTION_ABUNDANCE` | source-reported collection count | It does not fill `ticks_tested`, `ticks_positive`, prevalence, or abundance. |
| `testPathogenName` | `pathogen_name`, normalization envelope | harmonized exact target for approved pathogen mappings | `HardTick DNA Quality` and `Ixodes pacificus` are source-traceable non-pathogen assays and create no pathogen observation. |
| `testResult` | `ticks_tested=1`; `ticks_positive=1` for `DETECTED`, otherwise `0` for approved `NOT_DETECTED` | individual-test denominator/numerator | One nonblank individual result is eligible for its pathogen/stratum. No pooled interpretation is implemented. |
| package manifest, data/support files, variables, validation/categorical/readme resources | immutable artifact set and package manifest | acquisition provenance | Each package member has its own checksum, byte count, media type, stable manifest route, run, and package-manifest lineage. Temporary signed URLs are not retained. |

## Current governed state and consumer limits

The final #162 governed-DEV run completed ACQUIRE, VALIDATE, NORMALIZE, LOAD,
QUALITY, and PUBLISH_STAGE. It retained 31 request records and 31 distinct
immutable package-member artifacts, persisted 171 canonical records, and
recorded Tier-B publication `STAGED`. This is executable integration evidence
for the bounded source scope only. It is not approval for production, public
delivery, source expansion, county representativeness, prevalence aggregation,
or analytical comparability.

The implemented provenance chain is source dataset/product → frozen release →
source record → acquisition run → immutable package/member artifact →
transformation version → exact registry and mapping rule → validation/QUALITY
result → DEV staging state. Broader cross-domain semantic lineage remains
Story #193 work. The implemented checks do not replace the quality and
uncertainty methodology owned by #157.

Known limitations that consumers must retain are site-only/partial-county
coverage, variable sampling intensity, historical collection/taxonomy and
subsampling changes, impractical or missed collections, publication latency and
revisions, and non-random pathogen-test selection. These records do not support
individual disease risk, diagnosis, causal claims, or county-wide surveillance
coverage conclusions.
