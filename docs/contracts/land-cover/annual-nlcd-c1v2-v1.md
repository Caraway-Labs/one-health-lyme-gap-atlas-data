# Annual NLCD Collection 1.2 county-year v1

Status: candidate for protected source and scientific review under #196 and #202. Owner: Atlas data stewardship and engineering. This contract implements the existing #424 county analysis geometry, #426 immutable partition/revision behavior, and #432 named member replay. It does not authorize PROD publication, a score, an ML feature, or public/API admission.

## Source and canonical access

Use the official requester-pays `usgs-landcover` bucket in `us-west-2`. The Collection 1.2 CONUS root is `annual-nlcd/c1/v2/cu/`; both `mosaic/` and `tile/hXXvYY/` layouts exist. This implementation uses only exact bounded tile objects, never a mixed mosaic/tile run:

`annual-nlcd/c1/v2/cu/tile/h14v15/Annual_NLCD_H14V15_{LndCov|FctImp|LndChg}_2025_CU_C1V2.{tif|xml}`

The same key grammar applies to mapping years 1985–2025 and explicitly selected tile IDs. Each source definition is bounded to 1–16 sorted counties and tiles, a single mapping year, and a 512 MB aggregate acquisition cap (128 MB per artifact). A county whose selected tiles do not cover its full geometry fails closed. The initial [SourceDefinition](../../../config/sources/usgs_annual_nlcd_c1v2_2025_48081.yml) selects 2025, H14V15, and Texas county 48081. Routine full-history use requires additional reviewed bounded definitions with actual tile IDs; this contract does not guess them or authorize a national download.

Requester-pays S3 access uses the normal AWS SDK credential chain. A local operator may select a named profile with `AWS_PROFILE`; a cloud worker uses its approved workload credential mechanism. No profile name or credential is embedded in source code or the definition. The standard Tier-A CLI remains fixture-only or dry-run; the temporary live capture switch used during PR review is not part of the supported interface.

The three checked 2025 H14V15 TIFFs are 5,000 × 5,000 one-band 30 m WGS84 Albers Equal Area rasters (standard parallels 29.5° and 45.5°, central meridian 96°W, origin latitude 23°N). `LndCov` is uint8 with nodata 250, `FctImp` is uint8 0–100 percent with nodata 250, and `LndChg` is uint16 with nodata 9999. All use scale 1 and offset 0. The bounded S3 GETs returned requester charged and version IDs; object sizes were 2,873,383, 2,092,718, and 6,390,767 bytes respectively. The matching 2025 XML sizes are 34,679, 28,109, and 28,468 bytes. Exact XML product title, Collection 1.2 version, and publication date are validation gates. Object version, ETag, Last-Modified, retrieval time, member ID and SHA-256 are retained separately from observation year.

The 2025 TIGER/Line county ZIP is the SHA-256-pinned #424 analysis reference. The 3 TIFFs, 3 XMLs and TIGER ZIP are seven independently verified #432 replay members. The source-specific normalized row carries member digests and IDs, geometry/grid/weight identity and transformation version; generic #426 partitions and immutable captures continue to own physical revision and run-pinned reads. A changed source byte requires a new immutable capture even when a derived value happens to be unchanged. Historical original availability cannot be inferred from mapping year.

## Native categories and seven frozen measures

The approved `LndCov` codes are 11, 12, 21–24, 31, 41–43, 52, 71, 81–82, 90, and 95. The five area shares group forest 41–43, developed 21–24, agriculture 81–82, wetland 90/95, and open water 11. Each is class area divided by valid land-cover source-supported area. The sixth measure is the valid-area-weighted mean FctImp percentage explicitly divided by 100 to yield a fraction. The seventh is the valid-area-weighted share of changed pixels in `LndChg`: a native unchanged land-cover code is unchanged; an `AABB` code with valid different before/after classes is changed. Native class and transition areas remain in the normalized row. No fragmentation or phenology is inferred.

`LndChg` is labeled by the latter mapping year. The bounded 1985 artifact contains native transition codes, but the checked publisher evidence does not establish its earlier comparison period. Its native distribution is retained and `LAND_COVER_CHANGED_AREA_SHARE` is null with `UNVERIFIED_FIRST_YEAR_CHANGE`. The other six 1985 measures can be computed. This prevents an invented 1984 baseline.

The denominator is the valid product area within the union of non-nodata source support of all three products over the full legal county polygon. `source_coverage_fraction` is source-supported area divided by full 2025 TIGER county area; it is reported, not silently treated as 100%. A measure is numeric only when its product's valid area covers 100% of that source-supported footprint. A partially valid product remains null `PARTIAL_COVERAGE`; no supported area is null `SOURCE_MISSING`. Alaska/Hawaii are null `OUT_OF_SOURCE_COVERAGE`. A true numeric zero remains zero. The 100% within-support completeness rule is an Atlas engineering gate, not a USGS scientific constant. Exact boundary-cell intersection uses #424 geometry; full cells use projected area. All checks use the source's native 30 m grid.

The seven candidate #190 measures are in [annual-nlcd-semantic-measures-v1.json](annual-nlcd-semantic-measures-v1.json), and the #192 registry maps the initial bounded source definition. A semantic binding must match Collection, county, year, product, unit, denominator, completeness, approved source versions, all named member digests and IDs, and a single ingestion run. Reviewed #191 metadata, #193 source authority, #195 release compatibility, and #194 consumer exposure remain independent approvals.

## #202 compatibility and operator matrix

| Dimension | Required fact and gate | Failure or interpretation |
| --- | --- | --- |
| Collection/product | Exact C1V2 CU tile TIFF/XML pair for all three products | Legacy version, missing member, wrong title or changed native code blocks normalization. |
| Geography | 2025 TIGER canonical county, WGS84 Albers 30 m source grid, #424 area weights | AK/HI out of coverage; tile gap/overlap or changed CRS fails closed. |
| Time | Mapping year 1985–2025, county-year period | 1985 change prior period unverified; historical availability is separate from year. |
| Units | Native categories; impervious 0–100 percent; seven fraction outputs | Unit or scale drift blocks mapping; zero is not missing. |
| Completeness | Full legal polygon, tile intersection, union source support, product valid area and both fractions retained | Null partial/missing; no zero fill or hidden uncovered footprint. |
| Revision | S3 object metadata, SHA-256, retrieval and #426 capture/run | Changed bytes recapture; prior approved release persists until reviewed promotion. |
| Lineage | Six USGS members plus pinned TIGER, #432 exact replay, geometry/grid/weight IDs | Missing/corrupt member or cross-run substitution fails. |
| Scope | Contextual county-year land-cover evidence | No causal Lyme-risk claim, score, ML approval, PROD or public exposure. |

## Publisher sources

- [USGS Annual NLCD Collection 1 Science Product User Guide](https://www.usgs.gov/media/files/annual-nlcd-collection-1-science-product-user-guide)
- [MRLC Annual NLCD Land Cover Legend](https://www.mrlc.gov/data/legends/annual-nlcd-land-cover-legend)
- [USGS Annual NLCD Collection 1 overview](https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database)
