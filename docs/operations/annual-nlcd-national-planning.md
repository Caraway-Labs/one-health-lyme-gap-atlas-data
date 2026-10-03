# Annual NLCD national planning — DATA #444

Status: partial implementation for human review. The target remains **1985–2025
inclusive**, CONUS, Collection 1.2 and the seven frozen #196 measures. This is
not national coverage, approved execution, an ML eligibility decision or a
consumer release.

## Planning boundary

`ingestion.annual_nlcd_planning` extends the existing #196 SourceDefinition
model. It does not acquire, register, execute, approve or publish sources.

1. Retain an official requester-pays S3 prefix listing and its retrieval receipt.
   `tile_prefix_inventory` validates exact Collection 1.2 tile prefixes and
   rejects empty/duplicate/incompatible inventories. Never compute tile IDs
   from an assumed grid origin or use a mosaic.
2. Establish reviewed, version-pinned grid evidence. `TileGridEvidence.from_header`
   reads at most 64 KiB of each TIFF header, records **range** SHA-256 separately
   from full TIFF identity, and reuses #196 native CRS, resolution, dtype,
   nodata, scale/offset and 5000×5000 checks. A header digest is not a full
   governed capture. Retain source key, object version, ETag, retrieval receipt
   and header bytes together. XML remains independently required at acquisition.
3. Load the pinned #424 TIGER bytes using its canonical FIPS reconciliation.
   `county_required_tiles` requires evidence for every inventory tile and all
   three products for the selected year. It rejects cross-year substitutions,
   missing/duplicate grids, product-footprint drift and overlaps. It intersects
   the unsimplified county in the native equal-area raster CRS. Positive-area
   intersections select tiles; boundary-only touches do not. A geometric gap
   is explicit `TILE_GAP`; AK/HI are `OUT_OF_SOURCE_COVERAGE`. `TILE_COVERED`
   describes the geometric envelope, **not** non-nodata source support or
   product completeness. These remain #196 normalization facts.
4. Review the mapping and explicit gaps before acquisition. `bounded_definitions`
   groups counties by exact required tile set, in deterministic year/tile/FIPS
   order, with at most 16 counties and 16 tiles per definition. Each definition
   has one year. All six TIFF/XML sizes must be known, individually ≤128 MB;
   their sum plus the 83,989,800-byte pinned TIGER must be ≤512 MB. An oversized
   multi-tile county blocks; dropping a neighboring tile is prohibited.
5. `definition_document` emits JSON-compatible ordinary SourceDefinition input
   (also valid YAML). Review and retain those documents before using
   `atlas-data source validate --definition ...`, and only then the existing
   authorized `source run --tier B` and `runs show|explain|resume` commands.
   Tier A remains fixtures/dry-run. No live-local bypass is added.

The generated resource key includes mapping year and a digest of the sorted
county batch. Identical inputs produce identical definitions; tile/member order
and frozen scientific settings persist. A changed mapping requires reviewed
definition/revision handling. #426 partitions and immutable captures and #432
named members remain the acquisition, retry/resume and revision authority; this
planner creates no second checkpoint or artifact store. An unchanged capture
uses the existing content revision; revised source bytes do not overwrite prior
lineage. Generated definitions are not automatically admitted to semantic
mappings or releases.

## Source-backed early evidence (2026-10-03)

Baseline origin/main: `aab1041567e005e772c29b76ce48b4f7b3c48dc9`.
Existing #196/PR #435 were inspected. The isolated branch is
`feat/data444-annual-nlcd-national`; other agents' worktrees were not modified.

- Official CU tile prefix listing exposed **430 unique prefixes**. This says
  nothing by itself about valid pixels, counties or historical completeness.
- The listed `public_inventory.csv` is 29,784,450 bytes; GET returned
  **AccessDenied** under the existing laptop profile. No access policy changed.
- H14V15 object listing has **246 required objects** (41 years × 3 products ×
  TIFF/XML), totaling **455,652,258 bytes**. The listing has 738 total objects;
  only the three frozen products are selected. This is one tile's source
  availability and volume, not a national/history estimate or capture.
- H14V15 2025 required object bytes: **11,448,124**. Together with TIGER,
  one capture retains **95,437,924 bytes**, matching the #196 proof footprint.
- A 34,679-byte H14V15 Land Cover XML was inspected. Version
  `Zwe4sQhyfqg7padF0Rzajb8IqK_jXVJ0`, ETag
  `d81af29354ffd24bfe73522e0cc642e8`, SHA-256
  `d4a43d092f2c11bd3c0ff3cd70b5352cd0d5b1f8270c54432d989245af1a8e1a`.
- H14V15 2025 Land Cover TIFF 64 KiB header: object version
  `7X6CZekMgvDjz0nIjhUee_INOEmRpC.C`, ETag
  `d1b502122eb8df9505a3c88ec4e5a13e`, full object size 2,873,383 bytes;
  range SHA-256 `30f933d14b9a9b986b36dfbdaa43f2e565272de5cd5e752322d9bf588f6533f7`.
  Inspected native bounds: `(-465585, 914805, -315585, 1064805)`;
  WGS84 Albers, 30 m, 5000×5000. XML's geographic bounding envelope is not
  substituted for this exact native footprint.
- H15V15 2025 Land Cover header GET also succeeded: object version
  `eAczSZkFntoUCrqUTaLq5C21yBIqnHXC`, ETag
  `9c133d56db69a5716f49455029a82629`, full object size 5,783,632 bytes.
  Planner verification succeeded: 5000×5000, 30 m, native bounds
  `(-315585, 914805, -165585, 1064805)`, sharing an edge with H14V15.
  Range SHA-256 `6eb89328ab35d3162dbbafd040b73458aa46afdb914f657b1e3015f846383aae`.

These inspection bytes are outside the repository in the isolated task
workspace. They are not source run receipts or #432 governed capture manifests.
Metadata responses reported requester charged; measured charges are unavailable.
No full TIFF download, live local acquisition, DEV batch, PROD mutation,
consumer release or ML admission occurred.

## Operational estimates and remaining gates

`planned_footprint` reports bounded run count, normalized row count, unique USGS
keys/bytes, independent artifact captures, repeated per-batch TIGER retention
and requester-pays GET counts. It counts **repeated captures**, rather than
pretending unique upstream bytes are the retained footprint. Revisions and
retries add captures. Logical bytes are not Snowflake physical compressed bytes.

For H14V15 alone, one county batch for each of 41 years would retain
`455652258 + 41 × 83989800 = 3899234058` bytes before revisions and produce
246 requester-pays object GETs plus 41 TIGER retrievals. This is an arithmetic
planning example, not an approved 41-year execution or national extrapolation.
Different tiles have materially different object sizes (the two observed 2025
Land Cover files differ by roughly 2×). Do not multiply one sample across CONUS
as if it were measured national volume.

Requester-pays cost requires reviewed current region/request/transfer rates,
actual requests and retry counts; runtime and Snowflake compressed storage/
credits require a representative approved DEV pilot. Those facts remain
**UNKNOWN**, not zero. The national footprint cannot be defensibly computed
before the complete object inventory, mapping and county grouping exist.

Remaining work before broad execution:

- Complete reviewed tile/year/product grid and object inventory; establish exact
  #424 county-required-tile mapping and explicitly report gaps/multi-tile counties.
- Review a bounded metadata-only alternative to the denied publisher CSV; a
  prefix listing alone is insufficient. Do not assume historical footprint
  stability or that a metadata access failure means missing source data.
- Build the national longitudinal report from exact run-pinned captures,
  partitions, source-support/valid-area states and revisions. Distinguish
  NOT_ATTEMPTED/UNKNOWN from SOURCE_MISSING. The planner is not this report.
- Verify DEV runtime identity, preflight/migrations/artifact retention and
  explicit bounded pilot/budget; measure single/multi-tile and early/middle/recent
  samples through the existing governed runtime. No unattended national run.
- Preserve 1985 `UNVERIFIED_FIRST_YEAR_CHANGE` nulls; distinguish complete
  supported footprint from full legal-county source coverage; retain historical
  availability limitations for #110/#113 review without ML admission.

The story is incomplete until these evidence gates and the national panel are
delivered. Stop dependent source/scientific work when an authoritative inventory
or footprint cannot be established, as required by #444's ambiguity policy.

## Local validation and DEV readiness

Credential-free agent context: PASS. Ruff check/format and mypy: PASS.
Focused #196/#424/#426/#432 and initial planning tests: 58 passed. Final
planning tests, including synthetic native-header and JSON definition roundtrip:
10 passed. Source-backed planner inspection accepted both retained real headers;
it did not produce a county-year observation or a governed capture.

The Windows full suite had 3011 passed, 2 skipped and four unchanged
`test_failure_engine_launcher.py` child-startup timeout failures. Isolated
Windows reproduction: 2 passed, the same 4 failed. Those files have no diff
against origin/main; no unrelated timeout or permission behavior was weakened.
A container-local copy with the isolated clone's Git objects/refs (without
credential configuration) passed the final complete Linux suite: **3018 passed**,
20 third-party rasterio deprecation warnings. The initial copy omitted Git
history; the pinned historical-source test passed once that harness omission
was corrected. The earlier read-only Windows bind-mounted suite is auxiliary
environment evidence, not the successful final suite.

Local dbt parse, container build, packaged source validation and packaged dbt
parse passed. The container imported the planner and verified the 41-year
target. Wheel and source distribution built.

Canonical non-mutating DEV `pipeline preflight --operation governed_source_run
--environment dev` returned **UNKNOWN** for effective identity, migration ledger,
runtime capability, grant authority and approval. `mutation_started=false`.
This is a requirement plan, not a live identity or capability check. The
source-onboarding skill requires stopping dependent consequential work until
these prerequisites have authorized evidence. No grants, credentials, protected
deployment or live ingestion were changed to resolve them.

Subsequent authorized, bounded read-only inspection used the existing
`ATLAS_DEV_READ` connection. Effective role was `OH_LYME_DEV_READ`, database
`ONE_HEALTH_LYME_GAP_ATLAS_DEV`, warehouse `OH_LYME_DEV_INGEST_XS_WH`. Four
requested migration-ledger rows were visible: V069, V070, V103 and V117. Their
checksums all match using the repository runner's normalized-text convention,
not Windows CRLF file-byte hashes. This does not establish runtime capability,
deployed planner identity, artifact storage access, execution budget or approval.
No new identity, credential, grant, migration or deployment was created.
