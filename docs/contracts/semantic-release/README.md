# Governed semantic release contract

The semantic release is the product-facing data boundary for Epic #252. It is
assembled from approved, source-native records and is intentionally separate
from RAW, STAGING, and CONFORMED physical ingestion tables.

## Canonical model

```text
DATA SOURCE -> DATASET -> INDICATOR -> MEASURE -> OBSERVATION
```

`PRESENTATION.SEMANTIC_*` tables retain this hierarchy. Each observation also
retains its source version, ingestion run, immutable artifact, source row
identity/hash, retrieval time, geography and temporal semantics, transformation
version, quality state, value state, and limitations.

The API reads only these governed views:

- `PRESENTATION.CURRENT_RELEASE_V`
- `PRESENTATION.CURRENT_SOURCE_METADATA_V`
- `PRESENTATION.CURRENT_COUNTY_ATLAS_V`

## Release rules

1. The manifest pins the release identity and every source version, run,
   artifact, and artifact SHA-256. Placeholder values are rejected.
2. A source must have an active `APPROVED` or `CONDITIONAL` version, a
   completed ingestion run, an exact retained artifact, a staged/validated
   publication, and no failed blocking quality result. The sole DEV exception
   is the accepted Tier D county-status evidence path: it must instead have a
   source/run-pinned `UNKNOWN_SOURCE_COVERAGE` classification created by the
   owner-only procedure in V081. It contributes no source rows and renders both
   tick statuses as `Unknown`; it cannot represent no records, absence, or a
   successful routine ingestion.
3. The builder requires 3,144 unique five-digit county identities and a valid
   EPSG:4326 GeoJSON `Polygon` or `MultiPolygon` geometry for every county. It
   preserves the publisher geometry without Atlas-side transformation and fails
   closed on missing joins. A contextual source may retain valid additional
   source-native county rows outside this release identity, but it must cover
   every canonical county; the builder never manufactures values for a missing
   canonical join.
   Human-surveillance rows explicitly marked with `Unknown` or `Suppressed`
   state geography remain in their immutable source artifact but are not
   allocated to a county or state presentation record.
4. Release rows and observations are immutable after candidate creation. Only
   the current-release pointer and append-only release events change during
   publication or rollback.
5. The pathogen source is a separate manifest entry. The tick county-status
   workbook cannot satisfy the pathogen slot.

`governed-2026-09-15-manifest.template.json` is a review template, not an
executable release manifest. A protected release workflow must replace every
`REPLACE_WITH_*` value with evidence from the reviewed DEV run.
