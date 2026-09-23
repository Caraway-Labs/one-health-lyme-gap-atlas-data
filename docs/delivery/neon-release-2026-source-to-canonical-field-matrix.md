# NEON RELEASE-2026 source-to-canonical field matrix

Story: #162. Scope is strictly `DP1.10093.001` and `DP1.10092.001` at
`RELEASE-2026`; this is site/event surveillance, never county-representative.

| Product/table | Source field | Canonical behavior | Guardrail and lineage |
| --- | --- | --- | --- |
| 10093 / `tck_fielddata` | `siteID`, `plotID`, `eventID`, `sampleID` | v1.1 `sampling_site` and `sampling_event` | Native identifiers enter deterministic identity; no county natural key. |
| 10093 / `tck_fielddata` | coordinates, uncertainty | `source_geography` | WGS84 plot geometry is source-reported; county relationship remains `UNMAPPED`/`NOT_COUNTY_REPRESENTATIVE`. |
| 10093 / `tck_fielddata` | `collectDate`, `samplingMethod`, `totalSampledArea`, `samplingImpractical` | collection time/method/effort and quality context | Method and effort use #386; count is not normalized abundance without an approved denominator. Impractical is distinct from zero. |
| 10093 / `tck_taxonomyProcessed` | `subsampleID`, `scientificName`, `sexOrAge`, `individualCount` | `COLLECTION_ABUNDANCE` species/life stage/count | Exact #386 mapping envelope; unknown values block. Native row checksum, source record, artifact, run, and registry version remain retained. |
| 10092 / `tck_pathogen` | `subsampleID`, `testingID`, `batchID`, `testedDate` | `PATHOGEN_TESTING` identity/time | Individual-tick grain; duplicate or broken joins block. |
| 10092 / `tck_pathogen` | `testPathogenName`, `testResult`, `individualCount` | pathogen/result and tested/positive count | #386 only. Blank result blocks; one eligible test supplies one tested denominator; positive never exceeds tested. |
| 10092 / `tck_pathogenqa` | `batchID`, QA fields | source quality context | Retained without a row-multiplying join. |
| package support | manifest, variables, validation, categorical codes, readme | immutable artifact set | Every member has SHA-256, byte count, media type, stable requested route, run and package-manifest lineage. Signed download URLs are excluded. |

Known limitations remain explicit: site-only and partial-county coverage, variable
sampling intensity, historical taxonomy/subsampling changes, impractical/missed
collections, publication latency and revisions, and non-random pathogen-test
selection. No collection count is used as a test denominator.
