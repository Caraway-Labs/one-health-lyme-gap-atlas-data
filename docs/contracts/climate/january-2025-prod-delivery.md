# January 2025 native PROD delivery

DATA #443 / API #84. Execution is not authorized by this contract or a code merge.
The previous combined $25 inspection allowance has been consumed. No further
Snowflake session, source decision, grant, capture or pointer change has occurred.

## Retained live evidence

- DEV scientific inspection [38743325016](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38743325016): five reads, PASS, 8.06 seconds, no retry. County 48277 on 2025-01-17: PRCP 0 mm (ZERO); TMIN -1.992294192037333, TMAX 16.29939307942125 and native NOAA TAVG 7.153611977327104 degrees C. All COMPLETE. County 02013: four NULL / OUT_OF_SOURCE_COVERAGE / UNAVAILABLE observations. Original publisher availability remains UNKNOWN. Fraction 1.0000000000000027 is retained without clipping. This is not a test of partial January coverage or API access.
- PROD inspection [38743344162](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/38743344162): ten reads, PASS, 3.456 seconds, no retry. Exact NOAA/TIGER source-version and ingestion-run lookups succeeded with zero rows. No climate views were visible under the protected migrator; this is not inference from a denied read. V150 was pending and unrelated. Existing ATLAS pointer: `governed-2026-10-06-nlcd-demo-cohort`, bundle `603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9`. Reader role has database/PRESENTATION usage but no climate-view SELECTs.
- Both runs bound the account locator hash to TXB06009, region AWS_US_WEST_2. Owner evidence: VIFDGUW-BVB26657, AWS, Standard Edition. PROD warehouse: OH_LYME_PROD_APPROVAL_XS_WH, X-Small, generation 2, auto-suspend 60. Omitted cluster/QAS fields remain omitted; Standard entitlement is the separate capability evidence.
- Actual billed credits/cost are unavailable. The owner-supplied $2/credit public planning rate is not contractual billing evidence.

## Existing seams and invariants

The dedicated January SourceDefinition pins the accepted NOAA and TIGER bytes;
the original DEV definition and applied migrations are unchanged. The existing
routine-public collector retains the two binary objects and registers pending
candidates only. V151 extends the existing owner procedure with the exact pair,
resource-linked snapshots, actual named steward and January-only conditions.
Runtime cannot approve. Both resources receive separate immutable source versions
anchored to their evidence run/artifacts.

The existing Tier C orchestrator performs one native PROD run
`d0e1e30b-49f1-5400-8345-af0b3e975114`. It rejects an existing run or implicit resume.
Both actual approval identities are frozen in INSERT-only ingestion-publication
lineage. No DEV rows or DEV capture IDs are copied. Frozen input hashes are:

- NOAA: `809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31` (61,013,299 bytes).
- TIGER: `9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763` (83,989,800 bytes).

V152 reuses V147's scalar membership query and four metadata definitions with
COPY GRANTS on both views; it grants only their SELECT to OH_LYME_PROD_READ.
V151 executes as OH_LYME_PROD_OWNER, matching the existing admission procedure.
V152 executes as the protected migrator, matching the proven DEV climate-view
path and its direct capture-table read grant. No assumed owner-role capture-table
grant is introduced.

PROD extension v2 binds native run/artifacts, both evidence anchors, source
versions, 389,856 immutable memberships, content digest and four metadata revisions.
The prior accepted scientific content is reconstructed and checked; original
acceptance time stays unknown and its recording receipt is retained. Preparation
requires independent review of the exact merged implementation. It preserves the
entire current annual/NLCD manifest. Build and publication revalidate full source
approvals, native publication lineage, quality, revisions and canonical payloads.
The existing publication pointer is the only pointer. Generic deployment cannot
silently apply the new climate authority, and January release operations never
run migrations or legacy reconciliation.

## One consolidated protected execution request

Authorize the following dependency sequence at the final reviewed merged commit,
using existing GitHub production protection for every dispatch. Each stage gets
one attempt; a failure stops the sequence. No application/workflow retry or new
paid inspection is included. No historical or other-month ingestion is included.

| Order | Existing route / inputs | Identity / intended changes | Process limit |
|---|---|---|---|
| 1 | promote-prod.yml: january_climate_only=true, image_digest=january-climate-only, protected_intelligence_prerequisite=false, reviewed_commit=exact green merge, expected_pending_json=the committed January pending file | Existing PROD migration service; canonical runner validates full pending V150/V151/V152 and all applied checksums, then applies only V151/V152. V150 stays pending. Procedure owner switch only for V151; V152 adds two view SELECT grants. No app/image promotion. | 1,200s + 15s grace |
| 2 | capture-prod-routine-public-evidence.yml: config/sources/noaa_nclimgrid_daily_202501_prod.yml, release_commit=exact merge | Existing PROD pipeline service/OH_LYME_PROD_RUNTIME; retain exact NOAA/TIGER binary package and pending catalog evidence; no source approval or observations loaded. | 180s + 15s grace |
| 3 | Existing SP_RECORD_SOURCE_REVIEW_DECISION through actual MATTHEWCARAWAY / ATLAS_PROD_OWNER | Two owner decisions, NOAA then TIGER, APPROVED_WITH_CONDITIONS. CONDITIONS=['JANUARY_2025_ONLY','REUSE_OWNER_ACCEPTANCE_DATA443']; rationale records reuse of accepted January science; unique correlation IDs DATA443-JANUARY-PROD-NOAA and DATA443-JANUARY-PROD-TIGER. Record returned real version/decision IDs. No impersonation by a service identity. | One owner session, 180s + 15s grace |
| 4 | run-prod-ingestion.yml: operation=run, January PROD definition, planned run above, exact release_commit, actual NOAA source_version_id/source_decision_id returned at step 3 | Existing protected pipeline service; resolve and bind both active approvals; acquire both pinned original inputs and create native immutable PROD records, partitions, quality and STAGED ingestion publication. No semantic pointer mutation. | 18,000s + 15s grace (step 301m; bounded below hosted job maximum) |
| 5 | publish-semantic-release.yml: production, build, january_prod_delivery=true, prepare_january_climate=true, bounded_delivery=true, committed january-2025-prod-release-input.json, release_id=governed-2026-10-15-january-climate-prod | Existing protected migration service; require climate migrations already applied; freeze actual native membership/content and approvals, preserve annual/NLCD, build candidate. No V150 application. Private generated manifest is not uploaded publicly. | Preparation 3,600s + 15s; build 3,600s + 15s |
| 6 | Same existing release workflow: publish, January flag=true, prepare=false, bounded=true, exact release_id/input path/commit, confirm=true and owner reason | Revalidate candidate and atomically publish governed release/pointer. Then one bounded Data-identity scientific readback: actual eight representative observations, four metadata rows, published native run/source bindings; query IDs logged. | Publish 3,600s + 15s; readback 180s + 15s |
| 7 | Existing API #84 service-reader probe and permitted operational log surface; API owner coordinates fresh startup if needed | Actual configured API service identity using OH_LYME_PROD_READ; verify effective identity, four measures and same-release observation. No credentials exported, no API repository modifications, no activation inferred from Data identity. Actual decoded/public API acceptance and any activation remain API-owned gates. | At most existing three bounded probe reads; include 180s allowance |

For the source decisions use the existing procedure signature
`(resource_key, decision, rationale, conditions, reviewer_username, app_version, correlation_id)`.
APP_VERSION identifies the exact reviewed merge. Both real owner decisions must
join their retained evidence before step 4; an expired/unavailable owner credential
is a stop, not authorization to use service credentials or a browser substitute.

Every new executable January path checks effective account/region, role, suffixed
PROD database, fixed approval XS warehouse and live capacity before writes. Missing
visibility is a failed gate. Runtime warehouse USAGE and current effective owner
permissions still need live confirmation during that authorized execution; the
read-only inspection did not prove them. No speculative grants are included.
Statement timeout remains 60s, queue 10s and network 65s; connection retries are
disabled. Existing retained input/partition semantics are unchanged.

**Proposed combined forecast: $136.50; proposed maximum: $150.00.** This is a
conservative execution allowance, not a bill: 11 cumulative warehouse-active hours
(including stage guards, termination/auto-suspend tails and one explicitly scoped
rollback contingency) x 5.75 credits/hour stress envelope x owner public $2/credit,
plus $10 ancillary/storage allowance. Observed AWS XS Gen2 published consumption
is 1.35 credits/hour; 5.75 is the retained conservative envelope, not an observed
warehouse rate. Stop if actual account/capacity or planning-rate assumptions differ.
No global billing cap or contractual rate has been verified; unrelated warehouse
activity is not attributed to these runs. Retain query IDs and elapsed times;
actual billed cost remains UNKNOWN unless separately available without new paid reads.

## Recovery and acceptance

Before publication, failures leave the current NLCD release active. Preserve
partial captures and all evidence; do not recapture or resume automatically.
If an authorized publication fails acceptance, the existing protected rollback
route can restore the retained baseline release above (confirm=true, exact reason,
January delivery flag); its one-hour process allowance is included in the proposed
combined request. No history deletion or down-migration. A failed/partial DDL
requires inspection and a separately reviewed forward repair; do not manually
patch the ledger. Rollback is not an automatic reaction to an unknown query result.

Pass only after real PROD four-measure samples, native source/version/run/artifact
bindings, ZERO versus null/out-of-coverage, date/unit/coverage/provenance and current
release identity agree. V152 grants are necessary but insufficient: actual API
service-role reads and API-owned consumer/public-response acceptance are mandatory.
Keep API #84 and DATA #443 open until those gates pass. Do not activate the API from
Data-role access, fixtures, green CI or migration success alone.
