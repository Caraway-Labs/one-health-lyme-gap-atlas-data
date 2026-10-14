# DATA #443 January readiness and protected handoff

Audit date: 2026-10-13 (America/Denver). DATA main inspected:
`93085a246b7962a9bad1a3f095fb5630bdc1f08d`.
This is an evidence reconciliation and finite execution handoff, not execution
authorization. No Snowflake session, grant, capture, publication or deployment
was initiated in this audit. Current database state was not freshly queried.

## Acceptance matrix

| Requirement | Evidence and disposition |
| --- | --- |
| Frozen January capture | Recorded protected membership proof [37989552876](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/37989552876): run `c2eb2146-005d-44d2-bac4-e2805ca42577`, 389,856 capture IDs; membership SHA-256 `03f4ac5245e4d3006cbf3bf0948c4ef03862de838936ebd4df9c8448fed45ed8`. Reuse; no recapture. |
| DEV source/metadata admission | Recorded NOAA/TIGER conditional source versions and accepted four metadata definitions in [DATA evidence](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/443#issuecomment-6093207280); target source authority was revalidated by the protected builder. This audit did not reread source ledgers. |
| DEV candidate and publication | Recorded build [38014904454](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38014904454) and publish [38016599589](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38016599589): `governed-2026-10-09-january-climate-dev`, bundle `67cdf470a8c39973251d8325777132a840f63ee42b67f129973936c30e66d9f4`. GitHub publish success newly rechecked; current pointer is historical read evidence, not a fresh database assertion. |
| Observation view queryability | **Unresolved.** Newly inspected failed log [38019033858](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38019033858) stops at the observation SELECT with `000604 (57014)` after approximately ten minutes. LIMIT 4 did not resolve the query cost. Failure is not zero rows. |
| Existing performance implementation | [PR #669](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/669), head `555e7532a7962209014c430c91b3417cb1264e10`, remains OPEN/unmerged. No successor in the open-PR inventory. Main has no V147. Latest ten deploy-dev runs contain no later climate apply/readback. No claim of deployed or measured fix. |
| Regression and required checks | Newly rerun exact-head climate suites: **198 passed**. Existing exact-head [Quality 38118420943](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38118420943) newly verified SUCCESS: Ruff, format, mypy, full pytest, dbt parse, Docker/package, dry runs and secret scan. DEV image deployment job was SKIPPED. |
| Review/ownership | Peer review at `15d2e5a` resolved the snapshot schema finding. Later head `555e753` adds timeout controls; the PR explicitly requires renewed review and owner merge approval. Retain its implementation/worktree; no competing join or storage change. Other agents' worktrees were left untouched. |
| PROD January parity | Last documented inspection found no January source version/run/revisions and no applicable climate-view migration. PROD was not queried in this audit; later unrelated PROD promotions do not prove climate parity. |
| Intended API reader/public response | [API #84](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-api/issues/84) remains blocked on PROD publication and actual service-role reads. Dormant implementation exists; DATA tests do not establish API acceptance. |

Focused command, run from the unchanged PR #669 worktree with its `src` on
`PYTHONPATH` and the repository's installed Python environment:

```text
python -m pytest tests/test_climate_scalar_join.py tests/test_climate_dev_views.py tests/test_climate_numeric.py tests/test_climate_release.py tests/test_climate_publication.py tests/test_climate_source_review.py tests/test_metadata_snapshots.py -q
```

These are local relational/contract checks. They do not compile SQL in Snowflake
or measure source-backed performance. No new application tests are needed for
this documentation-only handoff. The implementation remains owned by #669.

## Smallest DEV action requiring owner authorization

1. Renew review of the timeout delta at #669's exact head; recheck ancestry,
   migration-number reservation and current-head CI against concurrent main.
   Green historical CI is not an approval to merge a stale branch.
2. Owner authorizes merge of the reviewed #669 implementation and a separate
   protected V147 apply after a read-only exact-pending-set/DDL/grants preflight.
   Proposed sole migration: `V147__dev_climate_scalar_membership_join.sql`,
   SHA-256 `22caabb8abb205316005d866286d7adb995a0b7dc5ec8b05aa6c6f053dfca83b`.
   If the actual pending set differs, stop and reconcile it; do not apply
   unrelated migrations under this approval.
3. Use existing `deploy-dev.yml` protected identity
   `OH_LYME_DEV_MIGRATION_DEPLOY_SVC` / `OH_LYME_DEV_MIGRATION_DEPLOYER`,
   database `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, warehouse
   `OH_LYME_DEV_INGEST_XS_WH`. V147 replaces only the observation view with
   COPY GRANTS; no source, membership, metadata, pointer or reader grant changes.
4. Separately authorize **one** existing protected readback via
   `verify_climate_views=true`; no retry. The prepared bounds are 60-second
   server statement, 10-second queue, 65-second socket/network, 300-second
   process plus 15-second kill grace, and ABORT_DETACHED_QUERY. Reserve **$10**
   for this readback only, subject to refreshed warehouse/edition/pricing
   assumptions in [the existing forecast](../contracts/climate/january-2025-dev-validation.md).
   This does not price or authorize migration apply, broader diagnostics,
   unrelated shared warehouse activity or PROD work. Obtain a separately
   bounded apply allowance before dispatch; its current forecast is not established.
5. Require exact ledger/body match and successful nonempty bounded observation
   read. Record elapsed time, query ID and sanitized output. A LIMIT 4 success
   is the performance smoke, not proof of all measures or complete delivery.

Rollback requires a reviewed **new** migration restoring V136's observation
body with COPY GRANTS, under separately authorized deployment controls. Do not
edit V136/V147 after application or move the release pointer for view rollback.
No source recapture or release rebuild is needed for this fix.

## Representative source-backed acceptance after performance passes

Prepare a separately reviewed bounded read matrix using the same protected view;
do not bypass it through RAW/revision-table reads. Bind every result to the
expected published release and verify the metadata relation has exactly the
four canonical IDs: `nclimgrid_prcp_county_day` (mm),
`nclimgrid_tmin_county_day`, `nclimgrid_tmax_county_day`, and
`nclimgrid_tavg_county_day` (degree_Celsius).

Choose January county/date tuples from retained accepted evidence rather than
inventing expected numerical values. Compare native numeric decoding, observed
PRCP zero and negative temperature, and AK/HI null OUT_OF_SOURCE_COVERAGE.
Verify observation labels lie within January 1–31, 2025 and represent NOAA's
labeled 24-hour period ending in the early morning. TAVG is native NOAA, never
derived. Preserve daily valid/source-supported fraction separately from monthly
source support; the 0.95 threshold applies only to the former. If partial or
source-missing states are absent in live January data, keep their fixture
evidence explicitly labeled. Historical publisher first availability remains
UNKNOWN; retrieval and upstream modification are distinct facts.

Retained NOAA input SHA-256 is
`809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31`;
2025 TIGER input SHA-256 is
`9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763`.
Use the existing [scientific contract](../contracts/climate/nclimgrid-daily-v1.md)
and [release validator](../contracts/climate/january-2025-release-extension-v1.md).
Do not substitute refreshed upstream bytes for retained accepted inputs.

## PROD preparation and owners

Repository inspection establishes the actual seams, independent of database
visibility:

- `run-ingestion.yml` rejects Tier C. Its January registration operation and
  `climate_source_review.py` are DEV/run pinned; do not generalize or bypass them
  merely to imitate a PROD approval.
- `capture-prod-routine-public-evidence.yml` admits SVI/RUCC/NLCD, not NOAA.
  A reviewed extension of this existing boundary may be needed for NOAA/TIGER
  target admission; first reconcile retained-input transport and target run
  binding with the source steward. No second source-specific workflow.
- `run-prod-ingestion.yml` already provides protected canonical Tier C run/resume
  with exact release commit and active target source version/decision IDs. Reuse
  this route after actual PROD admission; do not invent IDs or substitute DEV IDs.
  Its default 360-minute allowance is not a January cost approval. Prepare
  specific process/statement/disk/storage/credit bounds before execution.
- `publish-semantic-release.yml` supports protected PROD build/publish/rollback,
  but `prepare_january_climate=true` is intentionally DEV-only with the frozen
  DEV input file/release ID. PROD needs a reviewed target-pinned preparation
  through the existing manifest builder; changing an environment flag is
  insufficient. Never transport DEV capture IDs by assertion.
- V136 and proposed V147 are DEV-only. After DEV readback measures the accepted
  SQL, reserve the next available append-only PROD migration, verify effective
  owner/dependencies and existing grants, and review its exact pending set.
  No speculative migration number or persistent grant is proposed here.

Source steward must choose and approve the exact January-only PROD retained-input
admission/capture plan. Runtime owner must confirm least-privilege identity,
private immutable storage/cleanup, overlap exclusion and finite resource/cost
allowance. Release owner must approve the target manifest, exact frozen target
membership/content digest, four reviewed definitions, annual donor binding and
rollback target. View/access owner must verify target DDL and authorize any
necessary two-view SELECTs for the intended API identity, separately from raw
table access. All paid reads, capture, migration apply, publication and grants
need specific authorization; previous DEV approvals are consumed history.

Do not request a blanket PROD authorization now: target IDs, live prerequisites,
exact DDL/pending set and a cost forecast are not yet established. First approve
the DEV path above. A later PROD request must name every action, role, exact
input/run/release, stop conditions, allowance and rollback operation.

After PROD publication, API owner verifies the deployed service identity's
view-only reads against the same release, refreshes the existing service probe,
then uses normal controlled activation and verifies real public county responses.
Keep API #84 open and environmental context inactive until those gates pass.
No API or Web repository changes belong to this handoff.

## Longitudinal continuation

Preserve #443's 1985-to-latest-complete-supported-scaled-month target. January
handoff does not authorize a backfill or widen any published release. Reuse the
existing [longitudinal contract](../contracts/climate/nclimgrid-longitudinal-v1.md)
and [runbook](../operations/nclimgrid-longitudinal.md): separately approved finite
monthly tranches, reuse successful captures, frozen endpoint, explicit gaps,
immutable inputs and independent publication decisions. No ML feature admission
or disease-risk interpretation follows from climate delivery.
