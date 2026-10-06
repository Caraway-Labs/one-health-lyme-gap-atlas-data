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

## Protected execution

Source admission is pending execution. Matthew authorized this bounded PROD
delivery and up to **US$15 total for Snowflake load, staging, verification and
retries** on 2026-10-06 at 00:55 UTC. This separate authorization supersedes the
earlier proposed $1 limit; it does not consume or expand the prior acquisition
budget. No raster acquisition or national replay is authorized by this step.

After independent review, capture the candidate with the existing protected
`capture-prod-routine-public-evidence.yml`. V139 extends the existing owner-rights
review procedure to exactly this resource and immutable cohort evidence. Call
that procedure as the existing owner, recording Matthew's decision, the cohort
conditions and the independent review URL. The procedure generates the real
decision and source-version UUIDs. Its correlation ID permits an identical retry
to recover the first IDs; conflicting retries fail. Before a retry, reconcile
the actual correlation/run receipts. No user-supplied placeholder UUIDs are used.

The owner inherits the pre-existing Streamlit owner role with the required
INSERT/UPDATE table privileges; COPY GRANTS preserves procedure access. NLCD
approval requires GLOBAL, exact-resource or matching-catalog stewardship;
CDC/USDA domain stewardship alone cannot approve it. No grants are added.

Use the existing `run-prod-ingestion.yml` workflow with this
definition, exact reviewed `release_commit`, active `source_version_id` and
matching `source_decision_id`. That workflow requires the dedicated existing
PROD pipeline identity and protected production environment. A laptop audit
connection is not a substitute for that protected service identity. Runtime
must never approve its own source.

Build and publish using the existing `publish-semantic-release.yml`, with
`bounded_delivery=true`, an exact reviewed commit and a source-pinned manifest.
The additional `context_nlcd_2025` slot and `nlcd_extension` bind the actual
decision/version/run/artifact receipts, envelope checksum and independent review.
The existing 3,144-county / 44,016-observation baseline and restricted-source
publication attestations remain mandatory. The fourteen additional NLCD values
are context observations; they do not alter baseline scores or county identity.
Both publication and rollback validate all fourteen immutable V103 captures,
quality results, hashes, revisions and persisted semantic values before changing
the current-release pointer. V138 extends the existing consumer view using COPY
GRANTS, retaining its previous human rows. The 2025 planning-region observations
do not require or imply a crosswalk to the baseline 2022 geography.

## Bounded cost and runtime

Live metadata on 2026-10-06 confirms AWS_US_WEST_2 and existing single-cluster
STANDARD Gen2 X-Small ingest/approval warehouses, each with 60-second auto-suspend.
The documented consumer connection `ATLAS_PROD_READ` uses existing `COMPUTE_WH`,
an X-Small warehouse with 600-second auto-suspend. The consumer cannot use the
ingest warehouse; do not add a warehouse grant. Batch consumer readback into one
session and include its ten-minute idle period in the budget.

The [Snowflake consumption table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf)
effective 2026-10-02 specifies **1.35 credits/hour for AWS Gen2 X-Small** and a
60-second minimum per warehouse resume. Account-effective USD/credit is not
visible through the scoped connections. Forecast conservatively at the published
AWS Oregon VPS on-demand rate of **$6/credit**, also charging consumer time at the
higher 1.35-credit rate. This is a forecast, not an observed invoice or contract
price. Stop if an effective price above this ceiling or unbounded acceleration
or cluster expansion is observed; do not change warehouse configuration.

Bounded source operations set a 60-second statement timeout, ten-second queue
timeout and ABORT_DETACHED_QUERY in each canonical connection before writes.
Existing non-NLCD executions retain their current settings. SQL execution steps
stop after five minutes (identity checks after three); semantic operations opt
into the same limits. Laptop SQL must set the same session limits explicitly.
The operator must keep an attributable runtime ledger across attempts, with no
automatic retry. Stop at **40 minutes cumulative warehouse-active time plus
15 minutes of idle/resume allowance**, across all delivery sessions and retries:
55/60 * 1.35 * $6 = **$7.425 warehouse-compute forecast**. Reserve the remaining
**$7.575** of the authorized $15 for cloud services, request/storage charges and
uncertainty. Do not spend that reserve on another run without reconciling usage.
Cloud-services adjustments and account-level usage are not assumed to be free.

The unchanged derived artifact is 29,058 bytes. Candidate capture writes two
small private evidence/config objects; canonical ingestion retains one captured
envelope and bounded internal-stage transport, without copying ZIP/TIFF rasters.
Temporary stage transport is removed by the existing loader. The semantic build
retains the existing baseline plus fourteen rows, so storage includes its normal
release tables, not merely the small envelope. Record actual artifact sizes,
query IDs, elapsed windows and available credits separately from forecasts.
Metadata-only inspection is not evidence of zero billed cloud-services cost.

RAW/STAGING/CONFORMED load success and PUBLISH_STAGE's `STAGED` receipt are not
consumer publication. This MRLC extension preserves the original scientific
transformation and full mosaic lineage through the existing release machinery.
It does not claim to satisfy the separate USGS tile contract. Existing PROD_READ
grants cover both the county-observation presentation view and the secure V137
semantic-lineage audit view. Verify those two consumer surfaces after publication.

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
