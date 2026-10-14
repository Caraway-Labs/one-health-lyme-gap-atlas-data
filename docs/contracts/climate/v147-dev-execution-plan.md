# V147 DEV execution plan: prepared, not authorized

DATA #443 / PR #669. This plan executes no Snowflake operations. Each of merge,
metadata preflight, migration apply and observation readback needs its own owner
authorization. Protected DEV execution uses the resulting exact merged-main SHA
with successful Quality; PR-head CI alone does not authorize a main dispatch.

## Exact migration and preflight

Only proposed pending set:

```json
[{"version":"V147","filename":"V147__dev_climate_scalar_membership_join.sql","sha256":"22caabb8abb205316005d866286d7adb995a0b7dc5ec8b05aa6c6f053dfca83b"}]
```

The checksum is the repository migration loader's normalized UTF-8 source hash;
Windows CRLF working-copy byte hashes are not substituted. V147 is DEV-only and
changes only the observation view with COPY GRANTS. V136 and the metadata view,
source authority, frozen release membership and ATLAS pointer remain intact.

Prepared [metadata-only SQL](v147-dev-execution-preflight.sql) contains 18 serial
statements. Run it only after specific authorization under:

| Field | Required value |
| --- | --- |
| User | OH_LYME_DEV_MIGRATION_DEPLOY_SVC |
| Role | OH_LYME_DEV_MIGRATION_DEPLOYER |
| Database | ONE_HEALTH_LYME_GAP_ATLAS_DEV |
| Warehouse | OH_LYME_DEV_INGEST_XS_WH |

Use the existing service credentials; no local owner/ACCOUNTADMIN substitution,
secondary-role escalation, persistent grant or interactive authentication.
The prepared session must set server 60s/queue 10s limits and
ABORT_DETACHED_QUERY at login, socket/network 65s, with a 180s process deadline
and 15s kill grace covering the complete SQL bundle. No workflow/operator rerun;
authentication retry disabled. Connector transport requests can retry within
their existing deadline; that is not authorization for a second SQL attempt.

After successful reads, compare every ledger filename/checksum against
`load_migrations()` and existing authorized legacy reconciliation rules. Compute
the actual DEV pending set by subtracting applied versions from
`migration_plan(DEV_DATABASE)`. Require exactly the JSON tuple above. V149 is
DEV-eligible on current main: if pending, stop rather than apply it in this lane.
Duplicate ledger versions, more than 150 ledger rows, missing V136, unexpected
checksum, unavailable access or unexpected view definition also stop execution.
This is **not yet a live-verified pending set**; no ledger was queried here.

Verify effective schema/view ownership permits replacement, existing grants are
recorded for COPY GRANTS comparison, and migration-role dependency SELECT and
ledger INSERT authority exist. SHOW results may be privilege-filtered; unavailable
visibility is a stop, never absence proof or permission to grant. Validate V136's
compiled observation body and unchanged 14-column metadata/45-column observation
contracts before replacement. If V147 already has a matching ledger/body, do not
reapply it; reconcile the existing deployment instead.

The canonical CLI also invokes `reconcile_legacy_dev_migrations`. Preflight must
prove the existing reconciliation table and exact V028/V029/V033 rows already
match the canonical legacy and current source hashes, and the existing catalog
registration columns meet `REQUIRED_REGISTRATION_COLUMNS`. This makes its
`CREATE TABLE IF NOT EXISTS` and reconciliation checks no-ops. Missing or changed
legacy evidence requires a separate decision; no new legacy ledger row belongs
to this V147 approval. Recheck these conditions immediately before apply.

## Bounded protected apply, separately authorized

Existing `deploy-dev.yml` detects only the exact V147 tuple above. Its scoped
branch checks main ref, reviewed SHA, green checks and exclusive mode, validates
the actual service identity with the bounded connection, then calls the existing
`apply_reviewed_dev_migrations_command`. That CLI independently rereads pending
state before any migration; no second migration runner is introduced.

Prepared dispatch inputs: `expected_pending_json` = exact tuple;
`reviewed_commit` = exact merged-main green SHA; every diagnostic/registration
boolean false; query ID and January budget evidence empty. Use no feed allowance.
The inline process is bounded at 180s + 15s kill grace, with the existing opt-in
60s statement/10s queue/ABORT_DETACHED_QUERY limits on migration sessions and
zero authentication retries. The inherited migration session query tag is
`DATA594_BOUNDED_COHORT_DELIVERY`; do not use that tag alone for climate cost
attribution. Use exact service user, dispatch interval and returned query IDs.

Allowed durable effects are replacement of the single observation view and its
V147 migration ledger row. No ingestion, publication, pointer mutation, source
review or new grant. The legacy helper must have no new records to insert.

## Resource reservations: arithmetic verified, live assumptions gated

These **independent** proposed allowances are forecasts, not billed charges or
current authorization. They use the existing reviewed January assumptions:
Standard entitlement, single Standard Gen2 XS warehouse, no acceleration,
auto-suspend 60s, compute envelope 5.75 credits/hour, one-minute resume envelope
1.35 credits/hour, $6/credit and $1 noncompute reserve. The approved readback
maximum remains $10. No historical or other lane headroom is reused.

| Action | Conservative calculation | Separate allowance |
| --- | --- | --- |
| 18-statement metadata preflight | 315s x 5.75 x $6 / 3600 + 20 one-minute resumes x 1.35 x $6 / 60 + $1 = $6.71875 | Proposed $7 maximum |
| Sole V147 apply | 315s x 5.75 x $6 / 3600 + 40 one-minute resumes x 1.35 x $6 / 60 + $1 = $9.41875 | Proposed $10 maximum, independently approved |
| Existing observation readback | Existing 435s envelope + 15 one-minute resumes + $1, rounded upward | Existing $10 maximum; one attempt |

315s = 180s process + 15s kill grace + 60s final detached-statement allowance +
60s idle tail. The apply reserve includes identity, pending-ledger reads,
inherited legacy no-op checks, V147 DDL and ledger/commit overhead. Its 40-resume
envelope exceeds the application's SQL statements on the admitted sole-V147,
already-reconciled path; connector overhead remains covered by the time and
noncompute reserves. The readback keeps its existing 300s process + 15s grace
and 60s statement limit; its $10 ceiling is not increased.

Source/bound arithmetic is verified offline. Warehouse edition, size, clustering,
acceleration, auto-suspend and effective unit price are **not freshly verified**.
Obtain and compare authorized metadata/owner entitlement evidence before apply
or readback. Stop if assumptions differ or projected cost exceeds the applicable
allowance. These estimates do not cap unrelated activity on a shared warehouse.
Preflight itself requires its separate allowance and acceptance of the prior
warehouse assumptions before the first connection. No paid automatic retry.

## Single readback and recovery

After exact V147 ledger and compiled-body acceptance, separately authorize one
`deploy-dev.yml` invocation with `diagnose_climate_views=true`,
`expected_pending_json=[]`, `reviewed_commit` = exact green merged-main SHA;
all other modes false and query/budget inputs empty. The bounded verifier now
runs before the otherwise unbounded CLI identity query. It validates identity
inside its own connection and exits before migration dispatch. Limits stay
60s server / 10s queue / 65s network / 300s process + 15s grace. No operator,
workflow or application-level retry; authentication retry disabled.

Capture sanitized query IDs, elapsed time, exact body/checksum, grants and
nonempty LIMIT 4 observation output. Successful smoke is not completeness,
four-measure source-backed acceptance, PROD parity or actual API-reader proof.
Do not claim January fully consumable from that sample alone.

If apply times out or fails, do not rerun: Snowflake DDL can commit before the
ledger write. A separately authorized read-only inspection must reconcile the
actual view body/grants and V147 ledger. Never invent a successful ledger entry.
If restoration is required, reserve a new reviewed forward migration restoring
V136's observation body with COPY GRANTS, with its own execution allowance and
approval. Do not rewrite V136/V147 or change the release pointer for rollback.
Do not execute a speculative rollback now.
