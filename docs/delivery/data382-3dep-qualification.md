# DATA #382: USGS 3DEP qualification

Decision: **DEFER** implementation. Evaluated 2026-10-03 for
[#382](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/382).
This is an engineering qualification recommendation for human review, not a
steward approval or evidence of a delivered terrain portfolio.

## Evidence and bounded product decision

First-party pages inspected on 2026-10-03:

| Reference | Verified finding |
| --- | --- |
| [USGS products and services](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services) | 1/3 arc-second seamless DEM has broad U.S. coverage. Its approximately 10 m north/south spacing varies east/west. Project-based 1 m and the developing seamless 1 m portfolio are distinct products. Standard DEMs flatten water surfaces. |
| [USGS download FAQ](https://www.usgs.gov/faqs/what-types-elevation-datasets-are-available-what-formats-do-they-come-and-where-can-i-download) | National Map downloads are free without an account; 1/3 arc-second is offered as GeoTIFF, with COG distribution described. |
| [USGS product metadata](https://www.usgs.gov/ngp-standards-and-specifications/3dep-product-metadata) | Downloadable DEMs have product-specific XML metadata; spatial metadata describes source datasets. |

The **1/3 arc-second seamless bare-earth DEM** is the bounded candidate for
further evaluation. Do not substitute a dynamic elevation service, point-query
result, surface model, project DEM, or a nominal uniform 10 m grid. No product
is SELECTed for ingestion by this record.

## Why DEFER

Source availability alone does not demonstrate incremental Atlas decision value.
The ticket proposes elevation, slope, and/or ruggedness but does not specify the
consumer decision, a required scale, or a derivative algorithm. County mean
elevation is the smallest plausible descriptive candidate; it is not yet a
selected measure. Slope and ruggedness require independent justification,
explicit methods, neighbourhoods, edge handling, and resolution sensitivity.
No causal tick or Lyme risk interpretation is supported here.

No tile manifest, tile XML, raster header, or source-vintage spatial metadata
was captured in this evaluation. Consequently vertical datum, vertical units,
exact CRS realization, nodata value, tile revisions, acquisition periods, and
cross-tile compatibility are **UNKNOWN for an actual frozen input**. Program
descriptions are insufficient to assert uniform tile-level semantics. Attempts
to retrieve the linked seamless DEM specifications through the research tool
failed; this is an evidence-access limitation, not proof that documentation is
absent. No terrain raster acquisition or database action was performed.

## Conditions for reopening SELECT

1. Identify the concrete contextual decision and demonstrate why a specific
   resolution and minimum measure are sufficient. Record contextual-only
   status; #110 candidate admission requires its own review and evidence.
2. Pin the product identifier, tile IDs, URLs, checksums, byte sizes, product
   metadata, source acquisition periods, publication/revision dates and capture
   time. A download date is not a national observation vintage. Reject silent
   replacement at an unchanged URL.
3. Verify datum, vertical units, CRS and raster nodata from every pinned tile;
   fail on incompatible or undocumented inputs. Define any datum conversion
   separately with authoritative parameters and transformation lineage.
4. Use the existing [analysis county geometry contract](../contracts/county-identity-geometry/county-analysis-geometry-v1.md),
   not display polygons. For a proposed mean, review exact native-cell
   intersection area weights, land/water denominator, overlap/seam policy,
   minimum valid-area threshold and incomplete-status handling. Do not average
   angular-grid cells equally or replace missing terrain with zero.
5. Before implementation, freeze the method/version and source definition under
   canonical ingestion. Retain source/run/artifact/transform/geometry lineage
   under #188 rather than adding a parallel provenance mechanism.
6. Add targeted #202 tests for vertical datum and unit mismatch, angular versus
   metric resolution, CRS mismatch, tile overlap/seams, nodata versus true zero,
   partial county coverage, geometry vintage mismatch and revised artifacts.
   These are future acceptance cases, not tests claimed to exist in this PR.

## Delivery disposition

Qualification evidence and a defensible stop are delivered. Selected-scope
configuration, derivation, ingestion, #202 implementation and live proof remain
unfulfilled because the decision is DEFER. The ticket should remain open for
human review and resolution of the specific consumer/method/input choices above.
No schema, grants, PROD, ML admission or Web change is authorized by this record.

## Repository reconciliation

Starting main: `aab1041567e005e772c29b76ce48b4f7b3c48dc9`.
An isolated `codex/data382-3dep-qualification-20261003` worktree was created
from `origin/main`; a refreshed main was already identical. Current issue text,
AGENTS, the portable context index, source-onboarding skill/reference,
ADR 0027, canonical ingestion contracts, #424 geometry, and #188 metadata and
lineage contracts were inspected. The source-onboarding skill distinguishes
inspection from acquisition: this qualification starts no consequential source
operation. This standalone checkout has no assembled workspace governance file.

Repository search found no delivered 3DEP implementation. GitHub PR title search
for `3DEP` returned no prior PR. These are bounded searches, not a claim about
uncommitted work in other agents' worktrees. Their branches and sessions were
not modified. Repository context validation passes.

## Validation (offline only)

On the reconciled baseline and this documentation-only branch:
`uv run --no-sync ruff check .`, `ruff format --check .`, `mypy src` and
`dbt parse --project-dir dbt --profiles-dir dbt` pass using the frozen dependency
environment (472 formatted files; 112 typed source files). The repository
container build passes, image SHA-256
`2aab2937f928f50e7c0bcac7d0a1b7ffd593b628b54d0e17d549db9005f6002d`.
`git diff --check` and the credential-free context check pass.

The full pytest result is **3002 passed, 2 skipped, 4 failed** (800.83 seconds).
The failures are existing `test_failure_engine_launcher.py` spawned-child
success, cooperative timeout, disappearing child, and private-error receipt
tests, each receiving an outer-timeout result. A focused rerun on unchanged
main reproduces the same four failures (4 failed, 2 passed, 45.49 seconds).
Runtime/test sources are identical to main; this branch changes only this
qualification document. Host startup/deadline behaviour is a hypothesis, not a
verified root cause. No test deadline or unrelated launcher code was changed.
The suite is not represented as green. DEV, deployment, source-backed terrain
derivation and consumer validation were not performed.
