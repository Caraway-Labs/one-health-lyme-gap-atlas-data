# January PROD initial-PUT recovery

DATA #443. This is implementation scope, not protected execution authorization.

## Evidence and discrepancy

Owner-provided Snowflake forensics identify failed query
`01c7c061-030c-3303-0064-2d0701248012`, error 002003: the initial PUT to
`ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.INGESTION_BULK_STAGE` was unavailable
to `OH_LYME_PROD_RUNTIME`. ACQUIRE/VALIDATE completed, original NOAA/TIGER
hashes match, normalized partitions/completions and STAGING/CONFORMED output
are zero, and no competing native run exists. These are owner-supplied live
forensics; the recovery rechecks them rather than treating them as permanent.

The canonical registry classifies V117 as DEV-only. Retained protected PROD
inspection 38743344162 contains no V117 ledger row; V151/V152 later applied
without deploying a PROD bulk-stage counterpart. V117's immutable checksum is
`97dc205df634efdefa5dc561b36481068cfaa09dc6391d2acdc8cdf474add5e0`.
This establishes an omitted PROD dependency, not an applied-V117 checksum drift.
There is no evidence establishing that a PROD stage was dropped or replaced.
The 002003 alone does not distinguish physical absence from denied visibility.

V153 is the PROD counterpart: strict CREATE of the same internal SSE/JSON stage,
then only READ/WRITE to the existing PROD runtime role. V117 is unchanged and
not reclassified or retrospectively inserted in PROD. The canonical runner uses
the existing owner-role switch, enforces the full pending V150/V153 metadata set
and prior V151/V152 application, validates applied checksums, and applies only
V153. Generic promotion cannot apply V153. A preexisting stage stops strict
CREATE before the grant: no replacement, alteration, guessed configuration or
inference of absence from SHOW. Existing-stage permission-only repair would
require its actual configuration evidence and separate reviewed scope.

The shared streaming checkpoint and bulk projection paths use this stage for
other sources too. No transport path, storage architecture, source approvals,
warehouse, credentials or unrelated workflow behavior is changed.

## Exact recovery gates

Existing `runs resume` remains closed for January unless the explicit protected
recovery flag is true. Only run `d0e1e30b-49f1-5400-8345-af0b3e975114`, Tier C,
FAILED at its first NORMALIZE attempt, with completed first ACQUIRE/VALIDATE
attempts and untouched LOAD/QUALITY/PUBLISH_STAGE is admitted. Changed hashes,
versions, failed-stage identity, attempts or stage order stop before mutation.

The actual pipeline service must pass all six identity/capacity checks, read the
exact canonical V153 filename/checksum ledger entry, see an internal stage with
JSON/AUTO/MULTI_LINE=false and direct READ/WRITE, and rebind the original NOAA
and TIGER approval IDs. Both resources must have one active version; the only
native run must be this FAILED run. Any partitions, partition completion,
STAGING, CONFORMED, RAW, immutable revisions or ingestion-publication output
stops this zero-output recovery. Inaccessible metadata is a stop, never absence.

The durable Snowflake member store must match the original checkpoint manifest.
The existing adapter replays both checksum-verified retained binaries, including
their original source-definition digest, before any checkpoint is changed.
ACQUIRE is skipped; no HTTP recapture, source reapproval or new run is allowed.
The canonical state machine then increments NORMALIZE to attempt 2. Any later
failure is outside this recovery admission; there is no application/workflow
retry or automatic subsequent resume.

## One consolidated approval request

After independent review, merge and exact-main Quality, authorize both actions
at that exact merged SHA, within the existing cumulative $200 ceiling:

1. One `promote-prod.yml` dispatch: `january_bulk_recovery_only=true`,
   `january_climate_only=false`, `protected_intelligence_prerequisite=false`,
   `image_digest=january-climate-only`, `reviewed_commit=<exact green merge>`,
   `expected_pending_json=<contents of january-2025-prod-recovery-pending.json>`.
   Existing migration service switches only to `OH_LYME_PROD_OWNER` for V153;
   no image promotion. Max **$3**, process **180s + 15s** grace, one attempt.
2. Only after successful V153 application, one `run-prod-ingestion.yml` dispatch:
   `january_normalize_recovery=true`, `operation=resume`,
   `source_definition=config/sources/noaa_nclimgrid_daily_202501_prod.yml`,
   `run_id=d0e1e30b-49f1-5400-8345-af0b3e975114`, same exact `release_commit`,
   NOAA `source_version_id=94f08af7-8fa7-4452-987a-a7229f4b640d`,
   `source_decision_id=0de41cea-7fd0-4b9b-bd79-31fb2f879dde`.
   The existing runtime service performs the read-only stage/lineage/state gates
   above before any resume mutation. Max **$11.50**, process **1800s + 15s**,
   one attempt. This shorter recovery allowance replaces the original 18000s
   capture deadline for this opt-in only; it is not permission for a longer run.

Both dispatches require GitHub's human production review. Statement60/queue10/
network65/socket65 and disabled connection retries remain. No V150 or repeated
V151/V152, grants beyond V153's two stage privileges, history deletion, recapture
or pointer mutation is authorized here. No protected action was executed while
preparing this implementation.

Planning allocations previously total $185.50, not measured charges. The combined
new maximum **$14.50** fits the remaining planning allowance exactly, reaching
$200. At the retained 5.75 credits/hour stress envelope and owner public planning
rate $2/credit, (180+15+60 + 1800+15+60)/3600 * 5.75 * 2 plus $1 ancillary
allowance forecasts **$7.80417**. The rate is not contractual billing evidence;
actual billed totals are unavailable. No automatic additional allocation exists.

Failure stops the sequence. Snowflake DDL is not transactionally rolled back:
retain any created stage and migration receipt for reconciliation rather than
DROP, replace or edit its ledger. Do not rerun a partly applied migration.
Resume failure retains the original inputs and any new immutable output; do not
delete rows, reset attempts or remove retained transport as a rollback shortcut.
An owner-reviewed forward repair is needed for a new attempt. The semantic
publication pointer remains unchanged throughout these two actions.

After successful native capture, verify 389856 records, source bindings, quality
and STAGED publication before the existing governed build/publish sequence.
Preserve all annual/NLCD content. Actual PRCP/TMIN/TMAX/NOAA TAVG scientific
readback and API #84 service-role acceptance remain separate downstream gates;
no PROD availability is established by offline tests or this repair merge.
