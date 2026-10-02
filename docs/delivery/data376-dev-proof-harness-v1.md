# DATA376: offline DEV proof harness and cost handoff

Prepared 2026-10-02 from main `39f62f81893d25a06c98d8ec6a51110c0b16004c`,
after the independently reviewed opt-in adapter merge. PR570's scope packet is
still a proposal. Neither deployment of the dormant adapter nor this harness
authorizes a live proof, temporary DDL, new sink or activation.

## Reviewable candidate

`scripts/plan_failure_engine_dev.py` prints metadata-only JSON and its SHA-256.
Default invocation creates no connection, runs no SQL and writes no artifacts:

```text
uv run python scripts/plan_failure_engine_dev.py
```

The plan includes a code review pin, the actual local harness/helper file hashes,
the frozen public SQL-contract hash, exactly 28 operation IDs/SQL hashes and the
three fixed temporary destinations. It excludes SQL text, parameters, exception
text, usernames, credentials and personal paths. Invalid arguments emit only
PLAN_UNAVAILABLE. There is no live execution CLI switch. A supplied code pin is
not an actual workload observation; receipts retain actual_workload_sha and
independent_execution_verification UNKNOWN pending separate execution evidence.

`failure_engine_proof.run_proof` is the candidate session runner. A future
authorized caller must supply a fresh, dedicated existing ATLAS_DEV_READ
session, the unchanged reviewed plan and matching approved plan hash, plus the
expected configured user privately in memory. The hash pins scope; it is not a
credential or substitute for owner approval. Absent or mismatched approval
does not touch the session. This module creates/discovers no connection and
copies no credential; the launcher and its exact reviewed invocation
must remain within the existing named-connection policy. No interactive login,
alternate role, connection repair or persistent configuration edit is included.

## Exact operation and safety contract

The immutable, 4,650-byte public `failure_engine_proof_contract_v1.json` holds
source-derived V071 temporary-table definitions, current insert prefixes, the
first PR336 repair templates and V098's count-query kernel. Its canonical
SHA-256 is `d2ce120a0a08c9ff03b77a750613162cfd964d94305ab673db52dd09848f7b3b`.
Source/AST tests verify these against pinned, checksum-locked migrations and
the current helpers. A changed/oversized contract is rejected before planning.

The runner permits only its frozen operation IDs. Current `_insert_counties`
and `_insert_observations` execute through a boundary that accepts only their
four exact reviewed templates and exact synthetic parameters; the destination
is replaced with the corresponding fixed temporary name. Unknown SQL,
parameters, extra calls, repeated operations or row overflow fail before driver
execution. There is no general SQL command, caller-selected object or payload.

1. Verify effective private user, OH_LYME_DEV_READ, DEV database, configured
   warehouse and no existing transaction; reject mismatches before DDL.
2. Apply only session-local 30-second statement/15-second queue limits and a
   constant query tag. Check visible exact-name collisions; zero role-visible
   results are not proof of global absence. CREATE TEMPORARY uses no OR REPLACE,
   IF NOT EXISTS, cloning or live source-table reads.
3. Create only DEV.GOVERNANCE._DATA376_20261002_A_COUNTIES, _OBSERVATIONS and
   _CONDITIONS, then BEGIN TRANSACTION. No DDL occurs inside the DML transaction.
4. Run expected-negative PARSE_JSON-in-VALUES kernels and unbound CONDITIONS
   before positive writes. Accept only ProgrammingError errno 2014 or 904 for
   the corresponding fixed probe. The original PR337 run 35274411282/job
   105381395413 supplies bounded numeric 2014 evidence; no raw log/exception is
   retained. Unexpected success or another failure stops the run, rather than
   inventing historical reproduction or treating permission failure as expected.
5. Execute V098's actual DISTINCT/LEFT JOIN count kernel over generated synthetic
   CTEs: partial 3144/3143 with extras/duplicates, empty 3144/0 and full 3144/3144.
   This does not invoke or bypass the real procedure's PROD environment guard.
6. Exercise 50+1 county and 500+1 observation batches plus one VARIANT-array
   scripting insert. Verify counts, JSON types and release-ID replacement.
   Invalid row width must reject before the driver boundary.
7. ROLLBACK on every transaction exit, verify zero rows, then DROP only objects
   whose creation succeeded in this session. Failed/ambiguous creation is not
   guessed into ownership. Failed rollback skips DROP, so cleanup cannot commit
   an active transaction implicitly. Close cursor/session; any uncertain cleanup
   remains UNKNOWN and cannot produce a successful whole-run receipt.

Hard contract bounds: <=32 statements (28 intended), <=553 successful synthetic
inserted rows, <=1 MiB client fixture payload, one session/no retries/concurrency,
600-second wall planning budget. Generated canonical fixtures use <=3,147
logical rows including extras/duplicate, with no retained-source data.

The runner requires already bounded network/socket timeouts <=30 seconds before
any query; unknown/unbounded clients are rejected without touching or closing
them. It reserves 270 seconds for rollback, checks, drops and two closes. The
monotonic budget refuses new normal/cleanup statements when their 30-second
allowance would consume the reserve. These are statement-boundary controls,
not process preemption. `failure_engine_launcher.launch_proof` now starts one
spawned child with the fixed existing named connection and bounded login,
network and socket timeouts. It signals cooperative cancellation at 300 seconds
so normal statements stop and existing rollback/cleanup runs. At 590 seconds
it terminates only its own child Process instance, escalating to kill within
the 600-second envelope. No PID discovery, process-tree kill, role fallback
or reconnect occurs. The plan includes the launcher file hash. The default
plan CLI never imports or invokes the launcher. An explicit future invocation
requires the same unchanged approved-plan hash and private expected user. On deadline/cancel,
session-close verification can remain UNKNOWN; do not reconnect broadly or
delete unknown shared objects to force a green receipt.

## Resolved warehouse and cost estimate for the Word checklist

Read-only local named-connection settings observation on 2026-10-02 resolved:

| Field | Observation |
| --- | --- |
| Connection | ATLAS_DEV_READ |
| Configured role/database | OH_LYME_DEV_READ / ONE_HEALTH_LYME_GAP_ATLAS_DEV |
| Configured warehouse | OH_LYME_DEV_INGEST_XS_WH |
| Configured default schema | Unset; all fixture destinations are fully qualified |
| Read-only observed size/type | X-Small / STANDARD (2026-10-02); no size change |
| Observed auto-suspend / auto-resume | 60 seconds / true |
| Generation / clusters | UNKNOWN; missing cluster fields and no generation proof |
| Account USD/credit, discounts, incremental shared cost | UNKNOWN; no price assumed |

No credential values were emitted or stored. No live query was made for this
observation. The runner verifies the effective warehouse name again in the
future supplied session; the settings observation is not current live authority.

Compute planning formula: confirmed total credits/hour across running clusters
divided by six for ten minutes. Conditional example only: **if** this is a
single-cluster Gen1 X-Small warehouse, the published 1 credit/hour rate gives
about **0.167 compute credits** for ten minutes. It is not an observed size,
account spending cap or dollar estimate. Snowflake documents warehouse rates
and shared/multicluster considerations in its
[warehouse overview](https://docs.snowflake.com/en/user-guide/warehouses-overview).
Each resume has a one-minute billing minimum; warehouse idle/shared activity,
cloud-services charges and temporary storage make incremental total cost
uncertain ([warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-tasks)).
Do not resize/create a warehouse or assume a credit price to fill this gap.

For owner-review readiness, parent can obtain already authorized bounded
warehouse metadata through ATLAS_DEV_READ and privately resolve the applicable
rate. Otherwise record UNKNOWN and defer the live run. These are safe metadata
reads, not approval for this synthetic write probe. The actual probe still
requires the scoped decision, independent harness/launcher review and pinned
plan. There is no automatic new retention destination or failure-packet sink.

## Proof limits and handoff

Offline fake-session tests establish this harness's gates/control/cleanup,
not Snowflake engine behavior. Receipts expose only constant states, operation
IDs and validated UUID query IDs; missing/unsafe query IDs remain UNKNOWN.
Full V092 caller/steward/evidence behavior, V098 owner-rights/classification
ledger and PROD V099 permission enforcement remain UNKNOWN. Temporary ownership
cannot establish grants on real semantic tables. Repair remains UNKNOWN even
when this limited runner's checks pass; independently verify actual execution,
query identities and workload/artifacts before attaching behavioral evidence.

Parent owns independent candidate review and the existing Word owner checklist.
The optional DEV engine decision in PR570 is not yet approved; no live probe
was executed. No new credential/grant, DDL, scientific/product decision,
deployment, collector activation or real approval/release transition occurred.

Launcher offline tests use real spawned local children to check success, original
FAIL receipt preservation, cooperative cleanup, stuck-child termination and an
unrelated child surviving. OS process termination cannot prove server query
cancellation or session disappearance: both remain UNKNOWN on forced stop.
No broad cancellation query or guessed cleanup is issued. Runtime driver
version must equal 4.3.0 and is recorded; mismatch rejects before SQL. Unchanged
cursor query IDs are UNKNOWN, and unexpected negative-test success is explicitly
NOT_REPRODUCED with a safe stopped whole run.

Read-only post-commit metadata on 2026-10-02 reports the existing warehouse as
X-Small, STANDARD, auto_resume true and auto_suspend 60 seconds. Generation,
cluster count and account USD/credit remain UNKNOWN; this is not a cost cap.
No live synthetic probe or warehouse setting change occurred.
