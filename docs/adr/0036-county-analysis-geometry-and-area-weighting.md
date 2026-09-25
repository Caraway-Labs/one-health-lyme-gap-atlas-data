# 0036: County analysis geometry and area weighting

Status: Proposed for human review

Date: 2026-09-24

Decision owner: Atlas data stewardship and engineering

Story: #424; prerequisite to #198

## Context

The governed SVI 2022 county polygon is generalized for display. It cannot establish reproducible raster/grid boundary weights. Environmental observations may predate current county boundaries, while Atlas needs a stable comparable geography. The 2025 Census TIGER/Line county set exactly reconciles to the frozen 3,144-ID Atlas scope.

## Decision

Freeze the exact 2025 TIGER/Line County and Equivalent Entity National Shapefile artifact identified in `county-analysis-geometry-v1.md` as the first analysis geometry. Preserve SVI as display geometry. Join on five-digit GEOID/FIPS only. Retain original archive and geometry digests; reject invalid topology without automatic repair or simplification. Use source NAD83 coordinates in storage and fixed equal-area projections for intersection and area: EPSG:5070 for states/DC except Alaska/Hawaii, EPSG:3338 for Alaska, EPSG:2782 for Hawaii. Compute valid-area-weighted means from actual cell-polygon intersections with explicit nodata and completeness. Every historical environmental period uses the same frozen 2025 polygon vintage and carries that limitation.

## Consequences

The new geometry and weighting code is additive and storage neutral. Existing county identity, SVI semantic release, display map, API, and Snowflake relations stay as they are. A new environmental source must pin grid footprint CRS, values/units, nodata, completeness threshold, source artifact/run and this geometry artifact/method version before publication. The extra geospatial libraries are Shapely, pyproj, and pyshp; NumPy is bounded for Python 3.11 mypy compatibility. This decision grants no source approval or PROD access.

## Alternatives considered

- Generalized SVI or Census cartographic boundaries: unsuitable for area analysis.
- Cell-center inclusion: discards boundary-cell fractions.
- Area in geographic degrees: latitude-dependent and unsuitable as physical area.
- One CONUS equal-area projection for Alaska/Hawaii: avoidable distortion outside its intended region.
- Historical boundary reconstruction: outside this first frozen-panel contract.

## Acceptance criteria

Exact TIGER archive identity, county FIPS equality, valid nonempty topology, deterministic reprojection and weighting, area conservation, multipart handling, missing/partial distinction, source/transform lineage and display-versus-analysis distinction have automated or local source-backed evidence. No source repair is silently applied. Human review approves the contract before #198 consumes it.

## Rollout, observability, and rollback

This PR introduces code and documentation only. It does not load or publish DEV/PROD data. A future governed artifact/ingestion run and environmental publication require their ordinary gates. Rollback reverts the additive code and contract while leaving the fixed SVI release and county identities unchanged.

## Links to affected contracts and tests

`docs/contracts/county-identity-geometry/county-analysis-geometry-v1.md`; `docs/contracts/county-identity-geometry/county-identity-geometry-v1.md`; `src/lyme_gap_atlas_data/county_analysis_geometry.py`; `tests/test_county_analysis_geometry.py`; #188 semantic/lineage contracts.
