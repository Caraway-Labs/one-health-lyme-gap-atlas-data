# Local 2025 MRLC county calculation — DATA #594

This is an explicitly requested local calculation using the retained, verified
2025 CONUS capture from #597. It does not register a governed source, claim S3
version equivalence, change #444's historical scope, or authorize Snowflake,
production/consumer publication or ML admission. The seven #196 measures and
#424 unsimplified 2025 TIGER geometry and weighting method remain frozen.

## Compatibility and input identity

The three original official MRLC ZIPs total 4,269,391,159 bytes. Their nine
TIFF/XML/auxiliary members expand to 4,335,547,988 bytes. Exact package/member
SHA-256, CRC, HTTP ETag/Last-Modified and capture UTC times persist in the
original capture receipt. The local reader requires that reviewed receipt's
full digest, checks all original ZIPs and members before extraction, and verifies
all extracted members and the 83,989,800-byte pinned TIGER archive on each attempt.
Original ZIPs are read-only. Existing mismatches and unsafe names fail; completed
members are never overwritten. Interrupted `.part` files require explicit
owner reconciliation, not automatic deletion or replacement.

Observed mosaic grids are identical: 160000 × 105000, native WGS84 Albers,
30 m, affine `(30, 0, -2415585, 0, -30, 3314805)`. They align with inspected
tile-lattice evidence. Dtype, scale/offset, nodata and class validation reuse
#196; mosaic dimensions have a separate explicit gate. Native TIFF tags report
PixelIsArea; the observed GDAL affine is used without guessed half-cell shifts
or resampling. The official [USGS guide](https://www.usgs.gov/media/files/annual-nlcd-collection-1-science-product-user-guide)
and [MRLC legend](https://www.mrlc.gov/data/legends/annual-nlcd-land-cover-legend)
support the frozen categories, impervious percent and latter-year change codes.
XML title/product, Collection 1.2 and publication date are checked separately
from observation year and retrieval time.

## Calculation and limits

`ingestion.annual_nlcd_mosaic` is an offline disk reader, not a second ingestion
orchestrator. It reuses #196 `_pixel_weights`, class groups, nodata and change
decoder unchanged. It reads only native 256 × 256 windows. Exact boundary
intersections, full-cell projected areas, the union of three products' source
support, product-valid areas and the 100% within-support rule remain unchanged.
Partial validity is null `PARTIAL_COVERAGE`; no support is `SOURCE_MISSING`;
AK/HI have seven null `OUT_OF_SOURCE_COVERAGE` rows. Numeric zero stays zero.
No fragmentation, county-share differencing, causal-risk or ML measure is added.

Extraction needs 4.336 GB plus a 1 GB free-space reserve. All three compressed
COG files remain on disk together so each county's support union uses the exact
aligned products; national pixel arrays are never loaded. This laptop has
16 GiB RAM and eight logical CPUs. The reproducible PowerShell wrapper uses
the already cached runtime with 0.5 CPU, 2 GiB RAM, 64 PIDs, no network, no
credentials, read-only code/input mounts and a hard 60–1800-second deadline.
One invocation selects at most 128 new counties; use smaller proof batches first.
No automatic retry, loop, cloud compute or paid transfer is introduced.

Each completed county is exactly one seven-row partition in the existing #426
`FileCheckpointStore`. Input, software, grid, geometry, transform and Git/code
identities bind a deterministic local calculation run. Matching completed
partitions resume without recomputation; changed input/software identity creates
a distinct immutable run. Only the fully selected county set gets an existing
partition completion receipt. A timed-out unfinished county is recomputed on
explicit resume; large-county runtime must be measured before national expansion.
Stale exclusive locks block simultaneous or unreviewed restart. These local
partitions and content references are not fabricated governed artifact IDs.

Example (operator supplies existing owned local directories):

```powershell
./scripts/run_nlcd_mosaic_local.ps1 -Mode prepare -Inputs <input-directory> -Capture <retained-capture-directory> -Seconds 600
./scripts/run_nlcd_mosaic_local.ps1 -Mode calculate -Inputs <input-directory> -Output <result-directory> -Counties '02013,06075,09110,15001,48081,51013' -MaximumCounties 6 -Seconds 900
```

Record actual runtime, CPU seconds, peak RSS, partition bytes, eligible/processed
counties, product coverage/null states and source/software lineage. Prove repeat
execution and resumed partition hashes before expanding. A scientific mismatch
or failing frozen area invariant stops dependent calculation; never relax it
to manufacture a complete county panel. Local disk/output growth and elapsed
time must be reconciled between bounded batches. Existing shared cloud forecast
remains $9.805236 under $10; invoices are unknown. Laptop execution introduces
no new paid cloud compute/transfer category.

## Later Snowflake plan — held

Aggregate outside the database. Once independent scientific/code review passes,
prepare compact compressed county-year JSONL using the existing internal bulk
stage path, not pixels or an assumed Spaces external stage. Review source
admission, exact seven-row uniqueness, coverage/exclusions, lineage, immutable
revision and rerun behavior before a bounded DEV load. Set warehouse/time/credit
limits and validate set-based batches in short transactions. Promotion requires
its separate scientific/governance authorization. No Snowflake action is part
of this calculation request. Keep private operational receipts out of public
GitHub comments; publish only authorized aggregate findings and safe source URLs.
