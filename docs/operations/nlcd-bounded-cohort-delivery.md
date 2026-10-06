# Corrected Annual NLCD cohort delivery

This is a candidate governed admission of fourteen already calculated 2025
Collection 1.2 MRLC aggregate records: all seven frozen measures for Capitol
Planning Region, Connecticut (09110), and Arlington, Virginia (51013). It does
not establish national completion or a representative epidemiological sample.
No source downloads or raster calculations are needed for this cohort.

## Retained evidence

- Source definition: `config/sources/mrlc_annual_nlcd_c1v2_2025_demo_cohort.yml`.
- Captured derived envelope: `src/lyme_gap_atlas_data/data/annual-nlcd-2025-demo-cohort.json`.
- Exact envelope: 29,058 bytes; SHA-256
  `bdd2a4112769c894e069ae23021bb5a716313c3cfa821a7468aeaeebd2c451ee`.
- Original corrected calculation revision:
  `a1dca40aa049f5c8db4c819f20230843bc8041cf` (reviewed scientific repair PR #606).
- Original calculation run:
  `mrlc2025_12d3307d38bf247a467b03f42f48b4a3740fef66b30fcaa1b7ada31f926da499`.

The envelope retains the complete original calculation lineage, original county
partition receipts, official MRLC package/member digests and HTTP receipt
metadata, pinned TIGER identity, geometry digest, weight/transform versions and
calculation code identity. Every selected scientific record is unchanged. The
new ingestion capture is the real derived JSON envelope; it is not a raster
capture, a synthetic S3 tile, or a claim of USGS object-version lineage.

The adapter uses the existing source validation, capture, bounded partitions,
compressed internal-stage load, immutable V103 revisions and run resume path.
There are no new workflows, relations, roles or grants. Loads fail before a
connection is opened if the ACQUIRE artifact ID/checksum is absent or differs
from the reviewed envelope. The new normalization version describes adding the
canonical ingestion envelope; each nested scientific transformation version
remains unchanged.

`COMPLETE` means validity inside observed source support. Keep source support,
legal county area, valid area and source coverage fraction distinct. True zero
values remain numeric zero. Other counties are NOT_SELECTED, not zero or missing
source measurements. Connecticut 09110 uses the 2025 planning-region geography;
there is no historical county crosswalk. These are land-cover context measures,
not Lyme risk estimates or automatically admitted ML features.

## Protected execution and remaining decisions

Source admission is pending. After independent review and an owner-recorded
source decision, use the existing `run-prod-ingestion.yml` workflow with this
definition, exact reviewed `release_commit`, active `source_version_id` and
matching `source_decision_id`. That workflow requires the dedicated existing
PROD pipeline identity and protected production environment. A laptop audit
connection is not a substitute for that protected service identity. Runtime
must never approve its own source.

The acquisition/staging forecast is $9.805236073 against the shared $10 cap,
leaving $0.194763927 unallocated. The existing $2.29 uncertainty contingency is
already reserved and is not permission for a new run. Effective Snowflake
USD/credit is unknown. Proposed separate decision for the owner: permit at most
0.1 compute credits and $1 attributable new delivery spend, funded by an explicit
reallocation of existing contingency, only after confirming the credit price
keeps the total within $10. This is a proposal, not an executed budget change.
The observed existing warehouse is STANDARD_GEN_2 X-Small with 60-second
auto-suspend. No warehouse/resource/credential changes are proposed.

RAW/STAGING/CONFORMED load success and PUBLISH_STAGE's `STAGED` receipt are not
consumer publication. The existing Annual NLCD semantic mapping requires named
USGS tile TIFF/XML members; the real MRLC mosaic lineage cannot satisfy that
contract. A reviewed MRLC semantic mapping through the existing release machinery
is still required before consumer presentation. The observed PROD_READ grants
cover presentation views, not direct RAW/STAGING/CONFORMED or revision tables.
Do not bypass this boundary by inventing tile IDs or adding grants.

## Required readback proof after an authorized run

Scope revision readback to the actual returned ingestion run, resource key and
definition version, rather than first-write convenience projections:

```sql
SELECT COUNT(*) AS rows, COUNT(DISTINCT record_id) AS records,
       COUNT(DISTINCT artifact_sha256) AS captured_artifacts,
       COUNT(DISTINCT payload:record:county_fips::VARCHAR) AS counties,
       COUNT(DISTINCT payload:record:measure::VARCHAR) AS measures
FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
WHERE resource_key = 'mrlc_annual_nlcd_c1v2_2025_demo_cohort'
  AND source_definition_version = 1
  AND ingestion_run_id = '<actual-run-id>';
```

Expected: 14 rows, 14 records, one captured envelope, two counties and seven
measures. Verify the exact artifact checksum above, preserved source-row hashes,
original scientific lineage ID and scientific values against the retained
envelope. Resume the same run and repeat the count to prove no added captures.
Confirm its actual RAW artifact receipt and normalization version as well.
After the separately reviewed semantic release, use `ATLAS_PROD_READ` and the
existing presentation query to prove all fourteen values and their lineage are
consumer-queryable. Retain query IDs and effective role; no such consumer proof
has yet been executed.
