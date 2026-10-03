# DATA #380: EPA EnviroAtlas fragmentation/connectivity qualification

Decision: **DEFER** governed county implementation. Evaluated 2026-10-03 for
[#380](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/380).
This recommendation requires human review; it does not select a source for
acquisition, publish a measure or admit an ML feature.

## Specific candidate and first-party evidence

The bounded candidate is **Forest Connectivity - 2024**, file
`Forest_connectivity_CONUS_2024.tif`, service
[`Rasters/Forest_connectivity_CONUS_2024/ImageServer`](https://enviroatlas.epa.gov/arcgis/rest/services/Rasters/Forest_connectivity_CONUS_2024/ImageServer).
Agriculture connectivity, natural-area variants, Alaska's separate 2016 forest
product and the wider catalog are excluded from this candidate scope.

EPA's [national metadata workbook](https://www.epa.gov/system/files/documents/2025-04/enviroatlas_data_downloads_national.xlsx),
linked by its [download page](https://www.epa.gov/enviroatlas/forms/enviroatlas-data-download),
identifies the candidate in sheet `National - web map & download`, row 934.
The workbook was inspected as metadata only, not ingested as an Atlas dataset.
It labels the fact sheet as coming soon; the service XML nevertheless supplies
substantial method and class evidence. The dynamic matrix yielded only a
loading shell in this research client, so its absence of visible rows is not
evidence that the product is unavailable.

| Dimension | Verified evidence and limit |
| --- | --- |
| Product/time | Candidate title is 2024. Service XML describes temporal extent 2024-01-01 through 2024-12-31, a publication date of 2025-06-30 and processing steps dated 2025-05-01. The workbook calls it added June 2026. These are different metadata events, not interchangeable observation or first-availability timestamps. |
| Input/method | XML identifies Annual NLCD 2024 **C1V1** and GUIDOS Workbench 1.9.8 Simplified Pattern Analysis: 8-neighbour connectivity, one-pixel edge width, transition and intext enabled. |
| Foreground | XML includes NLCD 41, 42, 43 **and 90 (woody wetlands)**. This differs from Atlas #196's forest share, which includes only 41-43. |
| Native grid | Service advertises one U8 band, 30 m x/y cells and a custom WGS84 Albers CRS: central meridian -96, standard parallels 29.5/45.5, latitude of origin 23, false easting/northing 0, metre units. This is not a claim that it is EPSG:5070. |
| Coverage | Candidate is CONUS. Service extent is x [-2415585, 2384415], y [164805, 3314805] in its advertised CRS. A rectangular extent is not proof of valid coverage in every county. No AK/HI coverage is inferred. |
| Native values | XML labels 0 background, 1 branch, 3 edge, 5 perforation, 9 islet, 17 core, 100 interior background and 129 no data. The native attribute table contains these eight codes. They are categorical codes, not numeric connectivity magnitudes. |
| Nodata stages | XML's NLCD preprocessing uses 255 as input nodata; the output class dictionary calls 129 no data. These belong to different stages and must not be collapsed. The actual downloadable TIFF header and mask were not inspected. |
| Access/terms | XML declares unrestricted access and the EPA Public Domain License, linking [EPA's license](https://edg.epa.gov/EPA_Data_License.html). EPA offers downloads and public services. No national raster or county export was acquired. |
| Revision/cadence | No frozen downloadable artifact checksum, complete revision history or guaranteed refresh cadence was established. A service URL and a 2024 title are not an immutable source version. |

## Incremental meaning and reason for DEFER

The source definition establishes **structural**, rather than merely compositional,
information. A proposed core-area fraction within valid foreground could
distinguish spatial arrangements with equal total foreground area. This is a
logical implication of the documented core/edge method, not an empirical claim
about Atlas counties or Lyme outcomes. The raster's simplified pattern classes
do not establish organism movement, species-specific functional connectivity,
tick abundance or disease risk.

No county measure is SELECTed yet. A comparison with Atlas's existing forest
share would otherwise mix **C1V1 versus C1V2**, **2024 versus the initial #196
2025 definition**, and **forest-plus-woody-wetlands versus forest-only**.
Apparent differences could therefore reflect input vintage or foreground
definition as well as spatial structure. The specific unresolved choice is
whether to retain EPA's broader foreground as a separately named contextual
measure, and how to demonstrate incremental value against a compatible
same-year/composition baseline. Relabelling it as Atlas's existing forest
measure would be indefensible.

The second unresolved prerequisite is a reproducible, bounded transport and
artifact freeze: a downloadable TIFF's header, mask, class support, metadata
and revision identity must be verified against the service description before
county derivation. No source-backed county pilot has demonstrated this. This
record therefore stops at DEFER rather than replacing a raster inspection with
asserted constants or starting a national acquisition.

## Reopening contract and targeted #202 cases

A future SELECT must name one minimum measure, its contextual decision use and
exact denominator. A plausible candidate is core intersection area divided by
valid EPA foreground intersection area; it is **not approved here**. Background,
interior background, output nodata, no foreground and missing coverage require
distinct states. Averaging native class codes is prohibited. A zero denominator
must not produce a numeric zero or an invented connectivity score.

Use the existing [#424 analysis geometry](../contracts/county-identity-geometry/county-analysis-geometry-v1.md)
with exact native-cell intersection areas, the frozen 2025 county polygons,
explicit completeness criteria and source coverage diagnostics. Do not average
HUC12 summaries into counties, substitute display geometry or rerun SPA after
clipping a county: the latter changes the neighbourhood context. An existing
national categorical product should be aggregated as published, with boundary
cells and outside-county pattern context preserved.

Before implementation, freeze the downloadable product and revision, byte cap,
CRS WKT, grid affine transform, units, categorical dictionary, foreground,
nodata/mask behaviour, source observation vintage, publication/capture times,
refresh policy, geometry and aggregation method/version. Retain immutable
source/run/artifact/transform/geometry lineage through canonical ingestion and
#188. A service render or an unversioned resampled export cannot silently stand
in for the native downloadable raster.

Targeted #202 acceptance cases must cover:

- matched foreground/vintage versus C1V1/C1V2 and woody-wetland mismatches;
- class/NoData drift, input 255 versus output 129, real zero and zero foreground;
- custom WGS84 Albers versus EPSG:5070, changed grid resolution/alignment;
- partial support, out-of-source AK/HI, multipart/hole and edge-cell geometry;
- product revision at unchanged URL, cross-run members and missing lineage;
- equal-area-share synthetic arrangements with different structural classes,
  labelled as fixtures; a separate source-backed county pilot for actual input
  and aggregation compatibility.

These are reopening requirements, not test execution or a delivered ingestion
portfolio. The full source is not rejected: its structural meaning is promising,
but the bounded county measure and compatibility proof remain unresolved.

## Evidence receipts and repository reconciliation

The following public metadata was fetched on 2026-10-03 with a 1 MB cap per
response. These are local qualification receipts, not governed artifact IDs or
proof of unchanged future service contents.
The four exact service responses and their manifest are retained in
[`evidence/data380/`](evidence/data380/); the workbook receipt identifies the
local metadata probe, while the complete national workbook is not added to the
repository.

| Metadata | Bytes | SHA-256 |
| --- | ---: | --- |
| National workbook | 219920 | `dd783cf91cae3bb7d0f119ac041c9f3d102cbf3b09026cd0d551877aca08a6ea` |
| [Service JSON](https://enviroatlas.epa.gov/arcgis/rest/services/Rasters/Forest_connectivity_CONUS_2024/ImageServer?f=pjson) | 8907 | `2ac27cce208263875bd0dbf4f816d8d680678b293e610e42f5130533fcd9b97a` |
| [Service XML](https://enviroatlas.epa.gov/arcgis/rest/services/Rasters/Forest_connectivity_CONUS_2024/ImageServer/info/metadata) | 39339 | `dad3d51c5322f9089d5bcf3b7f38e619370f3f7ec022ca72ee2c74e5236f6c65` |
| [Class table JSON](https://enviroatlas.epa.gov/arcgis/rest/services/Rasters/Forest_connectivity_CONUS_2024/ImageServer/rasterAttributeTable?f=pjson) | 967 | `38980408a0235ec2ad8cd35aa5be84e77f8cf0ec5cc9bd281b5f12d537eece0c` |
| [Key properties JSON](https://enviroatlas.epa.gov/arcgis/rest/services/Rasters/Forest_connectivity_CONUS_2024/ImageServer/keyProperties?f=pjson) | 995 | `c256db6b28ae181baa4d7a6310bfb4b4622b2e01bb85b32bf2716ac135b68458` |

Isolated branch: `codex/data380-enviroatlas-qualification-20261003`.
Starting refreshed main: `aab1041567e005e772c29b76ce48b4f7b3c48dc9`.
Current issue, AGENTS, source-onboarding skill/reference, canonical ingestion
contracts, #188 metadata/lineage, #424 geometry and the delivered
[#196 contract](../contracts/land-cover/annual-nlcd-c1v2-v1.md) were inspected.
Repository context validation passes. Repository text and GitHub PR title
searches found no delivered EnviroAtlas implementation; this does not inspect
other agents' uncommitted work. No other agent's branch was modified.

The qualification decision is delivered; selected-scope ingestion, semantic
mapping, #202 implementation and consumer proof remain undelivered. Keep #380
open for human review. No database, PROD, grants, score, ML or Web action occurs.
