# V154 January climate delivery execution contract

Status: implementation prepared; **no new protected execution authorized**.
Owner directive is DATA #443 comment6227567077. Existing published release and
native ingestion are unchanged. One-shot diagnostic B .531s is not API acceptance.

## Reviewed scope

Use existing `promote-prod.yml`, `january_point_query_only=true`, other January
modes false, `protected_intelligence_prerequisite=false`,
`image_digest=january-climate-only`, `reviewed_commit` exact merged green main.
`expected_pending_json` is the complete live pending set: V150 plus V154 with
canonical filenames/checksums. Apply **V154 only**. Reject any other pending set,
missing V151/V152/V153, changed checksum or non-PROD database. V150 stays pending.
No image promotion, grants, source reads/ingestion, release/pointer write or
metadata-view replacement. Use the existing protected migration service and
OH_LYME_PROD_MIGRATION_DEPLOYER / OH_LYME_PROD_APPROVAL_XS_WH.

The existing 180s process deadline +15s kill grace applies, with statement60s,
queue10s, network65s, MAX_CON_RETRY_ATTEMPTS=0; no workflow/application retry.
The runner opens its existing identity, ledger, DDL and postcheck connections;
this is one protected workflow attempt, not a claim of a single session.
Pre/post snapshot validates the exact published January bundle, actual v2
manifest including sorted unique SHA string capture IDs, native run, declared
membership digest, V152/V154 normalized DDL, owner and all current view grants.
It does not recompute historical capture hashes or reread restricted CDC data.
COPY GRANTS preserves reader grants; DDL must run as current view owner.

Pre-DDL full-projection baseline/B parity uses the committed
`sql/january_climate_full_projection_parity.sql`: two counties48277/02013,
January17, four canonical measures, expected8 rows each, zero added/removed
complete rows. Count equality and set equality are checked separately. This
is bounded representative parity, not exhaustive389856-row runtime proof.
Offline relational parity covers every returned record/metadata/retrieval input;
the final scientific projection is byte-identical to V152, including VARIANT
stored types and native doubles. SQLite does not establish Snowflake types.

Post-DDL the same protected runner verifies the definition/grants/release and
reads every scientific column for the eight representative records (LIMIT9).
It verifies zeroPRCP, negativeTMIN, originalNOAA TAVG, exact units, null/unavailable
coverage and unique identities. It records query IDs and elapsed time; this
Data identity is not API proof. Result cache is disabled in this mode.

## Consolidated new authorization requested after green reviewed merge

Existing ceiling300; retained base reservations243 plus three consumed1-dollar
benchmarks = **246 reserved**, actual billing UNKNOWN. No reservation is released
because an operation failed or a conditional stage was unused. Manual owner
activity/shared warehouse traffic and invoices are not available to this agent.
This is a conservative planning ledger, not verified remaining cash.

Propose one delivery envelope **maximum35 additional**, preserving the300ceiling:

1. One protected V154 workflow with its pre/post scientific checks: maximum7.
2. One read-only postdeployment performance/profile session via explicitly
   authorized ATLAS_PROD_MIGRATOR on COMPUTE_WH: maximum7,180s+15s,60s statement,
   queue10/network65,resultcachefalse,no retries. Maximum12 statements: identity;
   SHOW warehouse; full-projection PRCP EXPLAIN; full-projection point once;
   bounded8-row read once; currentrelease/bundle; metadata4rows; own queryhistory
   for these2SELECT IDs; operatorstats for each2SELECT IDs; viewDDL; viewgrants.
   Stop on identity/access/resource/semantic failure; missing monitoring access
   is unknown and never permission to addgrants. No repeated performanceSELECT.
3. One existing API production redeployment/startup probe at its reconciled
   exact reviewedmain, climate stilldisabled: maximum7. ThreeSELECTmaximum,
   actual OH_LYME_API_SVC / OH_LYME_PROD_READ / COMPUTE_WH,5sstatementunchanged.
4. Only after serviceprobePASS: controlled ENVIRONMENTAL_CONTEXT_ENABLED=true
   through the current app configuration path, preserving every other setting;
   one healthydeployment and startup probe, plus eight canonical public HTTP
   observation requests (four measures each counties48277/02013 January17).
   Maximum7. Verify decoded units/values/coverage/provenance/dates, no geometry
   or restricted CDC data. No automatic HTTPretry. Onfailure disableflag and
   preserve evidence; never claimAPIacceptance fromDataidentity.
5. Reserve7contingency for reviewed forward rollback; this does **not** authorize
   speculative DDL or rewrite of V154 history. Any necessary rollback must be
   exact reviewed restoration of V152 body withCOPYGRANTS under protected owner,
   preservingrelease/grants, never release-pointer rollback or ledgerdeletion.

Forecast: four operation windows each <=195active/grace seconds plus600idle,
assumed1credit/hour, conservative20dollars/credit (notcontractual rate),25percent
contingency = **22.083334**, maximum28normaldelivery +7rollbackreserve =35.
Reservations become281/300,19unallocated, subject to no intervening allocations.
Stop if actual warehouseconfiguration/capacity or accepted cost assumptions
cannot be verified. No warehousealteration or timeoutincrease. Rollbackreserve
is retained, not evidence of actual spend. No duplicate/retry attempt allowed.

Required platform gates remain: exact-head independentreview, all requiredCI,
exact merged-mainQuality, GitHubproduction environment approval for eachprotected
workflow and owner-controlled appconfiguration. No deployment is dispatched
before this new consolidated execution scope is explicitly approved. These are
new operations; prior seven-statement benchmark authorization was consumed.

Acceptance: current published January release and bundle unchanged; all scientific
checks pass; actual API service observation under5s; eight decoded HTTP results
scientifically correct. KeepDATA443/API84open and climateoff until respective
real acceptance passes. NotifyWeb414only on acceptedAPIendpoint/contract.

Canonical V154 SHA-256: `087e24f350730176d805ecfda271b8c59e4507bb9bfd67067c430a94b0a74c35`.
