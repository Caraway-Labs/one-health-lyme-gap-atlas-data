# V154 protected production execution contract

Status: prepared, not execution-authorized. DATA #443 comment 6227567077 authorizes engineering and review; the completed benchmark allowance is consumed.

## Exact migration inputs

Use existing `promote-prod.yml` on exact reviewed, green merged main:

- `january_point_query_only=true`
- `january_climate_only=false`, `january_bulk_recovery_only=false`
- `protected_intelligence_prerequisite=false`
- `image_digest=january-climate-only`
- `reviewed_commit=<exact merged-main SHA>`
- `expected_pending_json` as below (the complete live pending set, not merely an execution subset).

```json
[
  {
    "version": "V150",
    "filename": "V150__prod_intelligence_raw_cleanup_authority.sql",
    "sha256": "883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"
  },
  {
    "version": "V154",
    "filename": "V154__prod_climate_membership_point_lookup.sql",
    "sha256": "087e24f350730176d805ecfda271b8c59e4507bb9bfd67067c430a94b0a74c35"
  }
]
```

Apply V154 only. V150 remains pending; V151–V153 must already be applied. Reject any other pending set or checksum, mixed mode or non-PROD database. No image promotion, source admission, ingestion, grants, metadata-view replacement or release-pointer write.

Use the existing protected migration service identity and `OH_LYME_PROD_MIGRATION_DEPLOYER` on `OH_LYME_PROD_APPROVAL_XS_WH`. GitHub production environment review remains required. Existing runner connections cover identity, ledger, DDL and postchecks; this is one workflow attempt, not a single-session claim.

Limits: 180-second process deadline plus 15-second termination grace; statement 60 seconds, queue 10 seconds, network 65 seconds; zero connection/application/workflow retries. Result cache is disabled for this mode.

## Acceptance before and after mutation

Before DDL, verify six-field identity, current warehouse capacity, the exact published January release/bundle, actual v2 manifest structure, native run and declared membership digest, V152 view body, current owner and reader grants. The manifest validator requires 389,856 sorted unique SHA string capture IDs. It does not silently normalize duplicates or recompute historical capture digests.

Warehouse assumptions use the prior owner-verified Standard Edition evidence bound to account locator TXB06009, not warehouse type as evidence of account edition. Standard Edition excludes multi-cluster and query acceleration capabilities. Missing SHOW fields remain unobserved; returned contradictory cluster counts or enabled acceleration block. Verify X-Small STANDARD, auto-resume and auto-suspend at most 600 seconds. A blank generation is not Gen1 evidence; forecast uses the conservative AWS Gen2 consumption bound.

The committed `sql/january_climate_full_projection_parity.sql` compares every output column between V152 and B for counties 48277/02013, January 17 and all four measures: eight rows each, zero added/removed rows. Count and set equality are checked separately. Filters and timeout bound acceptance scope/time, not physical scanning. This is representative runtime parity, not an exhaustive 389,856-row comparison.

Offline tests execute both relational branches over complete record/metadata/retrieval inputs, including zeros, negative temperatures, nulls, partial/out-of-coverage and excluded lineage. The final scientific projection is byte-identical to V152, including VARIANT stored-type and native-double fields. SQLite does not prove Snowflake VARIANT behavior.

After DDL, verify V154 body, exact grant and owner preservation, unchanged release/bundle/membership and full scientific projection for the same eight records (LIMIT 9). Verify original NOAA TAVG, finite numeric values, zero PRCP, negative TMIN, units, null/unavailable coverage and unique identities. Record query IDs and client elapsed time. Data-role results do not establish API acceptance.

## One consolidated new authorization request

Existing cumulative ceiling: $300. Retain $243 previous reservations plus three consumed $1 benchmarks = **$246 reserved**. Actual billing, shared traffic and manual owner activity are unknown; these are planning reservations, not verified cash availability. Do not release a failed or unused conditional reservation.

Proposed maximum incremental allocation: **$40**, within that ceiling:

1. One protected V154 workflow with the preceding scientific gates: maximum $8.
2. One read-only postdeployment diagnostic session via explicitly authorized `ATLAS_PROD_MIGRATOR` on `COMPUTE_WH`: maximum $8, 180 seconds plus 15-second grace, 60-second statement, 10-second queue, 65-second network, disabled result cache, no retries. Maximum 12 statements: identity; SHOW warehouse; full-projection PRCP EXPLAIN; full-projection point SELECT once; bounded eight-row SELECT once; release/bundle; four metadata rows; own query history for those two SELECT IDs; operator statistics for each SELECT ID; view DDL; view grants. Stop on failed identity, visibility, resource or scientific gates. Missing monitoring access never authorizes a grant or another attempt.
3. One existing API production redeployment/startup probe at reconciled exact reviewed main, climate disabled: maximum $8. Use actual `OH_LYME_API_SVC` / `OH_LYME_PROD_READ` on `COMPUTE_WH`; maximum three SELECTs and unchanged five-second statement cap.
4. Only after service probe PASS, set `ENVIRONMENTAL_CONTEXT_ENABLED=true` through existing controlled app configuration, preserving all unrelated settings. One healthy deployment/startup probe plus eight canonical public observation requests: all four measures for counties 48277/02013 on January 17. Maximum $8. Verify decoded values, dates, units, coverage and provenance, with no geometry or restricted CDC content. No HTTP retries. On failure disable the flag and preserve evidence.
5. Reserve $8 for reviewed forward rollback. This does not authorize speculative DDL or migration-history rewrites. Any required rollback must have an exact reviewed restoration of V152 body with COPY GRANTS under the protected owner, preserving release and grants. No automatic rollback, pointer rollback or ledger deletion.

Forecast: four operation windows, each 195 active/grace seconds plus 600 idle seconds, conservative 1.35 credits/hour and $20/credit planning allowance (not contractual pricing), plus 25% contingency = **$29.8125**. Normal delivery maximum $32 plus $8 rollback reservation = $40. Reservations become **$286/$300**, leaving $14 unallocated planning headroom, subject to no intervening allocations. Stop if observed resource assumptions exceed this scope.

No protected execution is dispatched before this new scope is explicitly approved. Preserve exact-head independent review, required CI, exact merged-main Quality, production environment approvals and owner-controlled app configuration.

Keep DATA #443/API #84 open until their real acceptance gates pass. Keep climate disabled until actual service acceptance. Notify Web #414 only after accepted deployed HTTP responses.

References: https://docs.snowflake.com/en/user-guide/warehouses-multicluster and https://docs.snowflake.com/en/user-guide/query-acceleration-service .
