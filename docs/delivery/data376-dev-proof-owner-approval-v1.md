# DATA376: bounded DEV proof approval packet

Prepared 2026-10-02 at main `581ea524f223c468422716d1cc368158aa59b45d`.
Audience: coordinating parent and the existing owner-review Word checklist.
Status: proposal only; no live SQL, objects, credentials or grants were changed.
PR568's opt-in collector is separately reviewed and is not needed for these probes.

## Decision to place in the owner checklist

**Approve or decline one synthetic DEV engine probe, maximum ten minutes, using
the existing ATLAS_DEV_READ connection and its existing warehouse, with three
session-temporary tables in ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE, at most
553 synthetic inserted rows, explicit rollback, explicit temporary-table drop
and session close. No permanent-object writes, new procedures, credentials,
roles/grants, warehouse creation/resizing, production calls, real approvals or
release-pointer changes are authorized by this decision.**

This is the only proposed new write/DDL authorization. The temporary-object
probe proves bounded engine behaviors, not complete historical repair. Approve
only after the parent has a reviewed, pinned harness matching the constraints
below; implementation and review are engineering work, not another owner ask.
If the existing connection/warehouse is unavailable or the effective context
differs, stop and report the blocker; this approval does not authorize repair of
access, interactive login, a new credential, alternate identity or new warehouse.

No request for broader privileges is made. Snowflake documents that temporary
tables do not require schema CREATE TABLE privileges and are session scoped;
normal connection/database/schema/warehouse usability must still be observed.
The [temporary-table documentation](https://docs.snowflake.com/en/user-guide/tables-temp-transient)
also explains their session lifetime and storage cost. This is why the existing
READ role is the first proposed identity, rather than OWNER or ACCOUNTADMIN.

## Observed versus required context

| Item | Evidence and required gate |
| --- | --- |
| Existing database | Exactly `ONE_HEALTH_LYME_GAP_ATLAS_DEV`; reject Alpha POC and PROD |
| Existing schema | `GOVERNANCE`, declared by V001; no schema creation |
| Connection / role | Inventory maps `ATLAS_DEV_READ` to `OH_LYME_DEV_READ`; current effective role UNKNOWN until a fresh identity read |
| Dated evidence | DATA372 snapshot `docs/generated/snowflake/dev-2026-10-02-current.snapshot.json`: generated 2026-10-02T01:36:13.683767-06:00, source live, inspected_role read, visibility partial; not proof of current access or complete object absence |
| Warehouse | Existing warehouse selected by ATLAS_DEV_READ; its exact name, size/rate and current usability are not published by repository evidence. Parent must record the resolved target before execution; do not substitute or resize |
| Current session/user | Not inspected here; match the existing authorized connection privately and publish only match/PASS or UNKNOWN, never username/credentials |
| Access surface on this laptop | No `snow` executable found on PATH in the prior audit; no credentials inspected. An unavailable tool/connection remains a blocker, not permission to change credentials |

Fresh bounded identity observation must precede consequential work. The
existing `semantic_release` preflight is UNKNOWN for identity, ledger,
SEMANTIC_RELEASES INSERT, authority and protected approval; mutation_started=false.
It does not authorize a candidate build. The proposed fixture is a new synthetic
engine test, not a protected semantic-release invocation.

## Safe existing reads, separate from the approval above

The parent can coordinate these under the already authorized DEV inspection
scope using ATLAS_DEV_READ, without creating objects:

1. One effective user/role/database/warehouse SELECT, private identity comparison;
   emit only the canonical role, DEV match, warehouse match and query ID if allowed.
2. Bounded metadata of only GOVERNANCE and PRESENTATION, and the exact targets
   in the tables below. Observe object types and visibility; invisible is UNKNOWN.
3. Read `GOVERNANCE.SCHEMA_MIGRATIONS` only for V071/V072/V073 and the four
   PROD-only incident versions V091/V092/V098/V099. Report version/hash evidence
   or UNKNOWN; their expected exclusion from DEV is not an unapplied-DEV defect.
4. If ordinary metadata visibility permits, read grants only on the nine named
   semantic tables for OH_LYME_DEV_MIGRATION_DEPLOYER and OH_LYME_DEV_READ.
   Do not expand to SHOW GRANTS over all roles/users or use ACCOUNTADMIN.
5. Optionally evaluate <=3 pure SELECT synthetic probes: outer PARSE_JSON over
   bound VALUES, the V098 canonical DISTINCT/LEFT JOIN kernel using generated
   synthetic relations, and VARIANT parameter selection in a read-only anonymous
   scripting block. No retained data rows, mutation, procedures or external I/O.

These reads may incur existing-warehouse query cost. Use <=30-second statement
and <=15-second queued-time limits and stop after at most 20 read statements.
Private identity or catalog details do not belong in public packets. The parent
may reuse appropriately scoped recent DATA372 evidence instead of re-reading.

## Proposed temporary objects and permitted operations

All names below are proposals, not claims that these objects currently exist.
Full qualification is mandatory; no unqualified/default-schema writes.
The complete proposed column definitions are reviewable in
[`data376-dev-proof-proposed-ddl-v1.sql`](data376-dev-proof-proposed-ddl-v1.sql),
extracted from the baseline's V071 definitions with only the creation mode and
destination changed. This file is not a migration and has not been executed.

| Exact proposed object in DEV.GOVERNANCE | Type / definition source | Permitted operations |
| --- | --- | --- |
| `_DATA376_20261002_A_COUNTIES` | SESSION TEMPORARY TABLE; full column definition from V071 `PRESENTATION.SEMANTIC_COUNTY_ATLAS` at the baseline SHA, with only destination name changed | CREATE TEMPORARY TABLE; INSERT through the current `_insert_counties` path with exact object-name redirection; bounded SELECT of synthetic counts/hashes; DROP owned session table |
| `_DATA376_20261002_A_OBSERVATIONS` | SESSION TEMPORARY TABLE; full column definition from V071 `PRESENTATION.SEMANTIC_OBSERVATIONS` at the baseline SHA, with only destination name changed | CREATE TEMPORARY TABLE; INSERT through current `_insert_observations` with exact object-name redirection; bounded SELECT of synthetic counts/hashes; DROP owned session table |
| `_DATA376_20261002_A_CONDITIONS` | SESSION TEMPORARY TABLE `(conditions VARIANT)`; synthetic one-column binding target | CREATE TEMPORARY TABLE; at most one INSERT via SQL Scripting SELECT `:CONDITIONS`; SELECT only count/type/hash; DROP owned session table |

No CREATE OR REPLACE, IF NOT EXISTS, LIKE, CLONE, CTAS from existing tables,
permanent table/view/procedure/stage creation, GRANT, REVOKE, ALTER ROLE,
warehouse DDL, source data reads, real approval or publication CALL is included.
The harness must fail closed for any statement outside these exact temporary
destinations or pure synthetic queries. Check visible name collisions before
creation and abort on collision or ambiguous object ownership; never replace or
drop an existing object. Record successfully created temporary names in memory;
cleanup may target only that recorded set in this same session.

## Behavioral checks and proof limits

| Incident | Proposed checks / expected negative | What remains UNKNOWN |
| --- | --- | --- |
| PR336 / PR337 | Locked connector 4.3.0, pinned helper source; 51 synthetic counties and 501 observations exercise 50/500 batching, order/release-ID replacement and server PARSE_JSON acceptance. Run the first repair's PARSE_JSON-in-VALUES form against the same temporary destination expecting engine rejection; record an unexpected success as NOT REPRODUCED, never manufacture failure or expose exception text. Invalid row width must fail before server write. Verify rollback returns temporary counts to zero | Historical actual checkout/image/client version and release-level persistence/deployment; a current server may differ from the historical server |
| PR353 / PR354 | Anonymous SQL Scripting block with local CONDITIONS VARIANT; unqualified CONDITIONS in INSERT SELECT is expected to fail name resolution, explicit `:CONDITIONS` must insert one synthetic array correctly. Catch only approved bounded error category, then rollback. No procedure is created | Full V092 caller-rights procedure, steward/evidence gates, live approval ledger and deployed PROD behavior |
| PR365 | Pure SELECT uses the actual V098 DISTINCT/LEFT JOIN count kernel with synthetic canonical rows: 3,144 canonical, 3,143 reported canonical plus <=10 out-of-scope extras and duplicate rows. Expected reported=3,143/unresolved=1; empty or fully covered fixture must not be claimed eligible partial coverage | Actual owner-rights procedure and classification ledger. Its literal CURRENT_DATABASE PROD guard is retained in the real migration and is not bypassed for DEV |
| PR366 | Fresh DEV metadata can identify role-visible desired privileges. Optional read-only EXPLAIN may provide compilation evidence, explicitly labeled as such | Actual V099 PROD privilege enforcement and intended-role mutations. Temporary tables are owned by their creating session and cannot prove rights on real semantic tables |

Bounded synthetic fixtures prove selected behaviors only. They do not turn a
PROD-only repair packet into repair PASS. Append a companion behavioral receipt
with exact harness commit/run/query IDs and remaining unknowns; preserve all
original historical packets and DATA377 frozen expectations. Any newly observed
failure gets the existing strict DATA376 packet, without raw exceptions, SQL
parameters, secrets, personal paths or source/user data.

## Actual historical objects: excluded from the temporary-write request

V091/V092/V098/V099 are in `PROD_ONLY_MIGRATION_VERSIONS`; V098 also rejects
any database other than ONE_HEALTH_LYME_GAP_ATLAS_PROD. The real targets are:

| Existing normative target | Type / signature | Real mutation to avoid |
| --- | --- | --- |
| GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD | SQL procedure, EXECUTE AS CALLER, `(VARCHAR,VARCHAR,VARCHAR,VARIANT,VARCHAR,VARCHAR,VARCHAR)` | Retires DATA_SOURCE_VERSIONS, inserts source version and MANUAL_REVIEW_DECISIONS after approval/evidence checks |
| GOVERNANCE.SP_CLASSIFY_RESTRICTED_PATHOGEN_PARITY_PROD | SQL procedure, EXECUTE AS OWNER, `(VARCHAR,VARCHAR,VARCHAR)` | Reads CONFORMED.GOVERNED_SOURCE_RECORDS, CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS, GOVERNANCE.INGESTION_RUNS/DATA_SOURCE_VERSIONS; inserts GOVERNANCE.RESTRICTED_PATHOGEN_PARITY_CLASSIFICATIONS |
| PRESENTATION.SEMANTIC_RELEASES | TABLE; V099 intended executor SELECT/INSERT/UPDATE | Candidate/status writes |
| PRESENTATION.SEMANTIC_DATA_SOURCES, SEMANTIC_DATASETS, SEMANTIC_INDICATORS, SEMANTIC_MEASURES, SEMANTIC_COUNTY_ATLAS, SEMANTIC_OBSERVATIONS | Six TABLES; V099 SELECT/INSERT | Immutable release content writes |
| PRESENTATION.SEMANTIC_RELEASE_EVENTS | TABLE; V099 INSERT | Append-only real release event |
| PRESENTATION.SEMANTIC_RELEASE_POINTER | TABLE; V099 SELECT/INSERT/UPDATE | Published release-pointer transition |

The procedure inventory/signatures above are source declarations, not live
existence or ownership observations. V099's real role is
OH_LYME_PROD_MIGRATION_DEPLOYER; a DEV analog cannot establish these PROD grants.
No production execution or privilege change is requested here. If an owner
wants full intended-role proof later, the parent must prepare a separate exact
production scope; this packet is not blanket authorization for zero-row INSERT,
UPDATE/DELETE, approval-negative CALLs, procedure replacement or role switching.

## Duration, cost, cleanup and recovery

Proposed hard bounds: one session, existing connection/warehouse only, ten minutes
wall time including cleanup, <=32 engine statements plus <=20 preliminary reads,
<=30 seconds per statement, <=15 seconds queued time, <=553 inserted synthetic
rows and <=1 MiB client fixture payload. Synthetic V098 SELECT generates <=3,200
rows. No retries or parallel queries. Stop on deadline, identity mismatch,
unexpected SQL/object, inaccessible dependency or failing negative check.
Run historical expected-negative cases before positive writes; if a negative
unexpectedly succeeds, rollback and stop rather than continue accumulating rows.

The existing warehouse's size, contract rate and current activity are UNKNOWN
here, so no dollar/credit estimate is invented. Record its existing size/rate
privately before execution; incremental upper planning bound is ten minutes at
that existing rate, subject to warehouse billing minimums and shared activity.
This is a query-duration budget, not a hard account spending cap. If the parent
cannot identify an acceptable existing rate/warehouse, defer the live probe.

Create all temporary tables before starting DML. Then BEGIN TRANSACTION,
execute each bounded case, ROLLBACK on every success/failure exit, and verify
zero temporary rows. DROP only temporary tables created by this session after
rollback; then close the session. Never issue DDL or change AUTOCOMMIT inside
the active DML transaction: Snowflake DDL implicitly commits and cannot be
undone with rollback ([transaction documentation](https://docs.snowflake.com/en/sql-reference/transactions)).
No real-table repair, DELETE, migration or release rollback is a cleanup step.
If cleanup fails, close the session and report UNKNOWN cleanup verification;
session-temporary objects expire with that session. Never reconnect under a
broader identity to force cleanup. No created shared object should survive by
design; if one is unexpectedly observed, stop and involve the coordinating
parent rather than deleting it.

## Why existing fixtures and read-only alternatives are insufficient

Merged PR566 runs the actual client's local rewrite/conversion paths but stops
before transport, so it cannot establish Snowflake's INSERT/VARIANT behavior.
The existing DEV CDC scripts run different CDC quality/publication paths under
RUNTIME against temporary tables; they do not exercise these semantic inserts,
V092 SQL Scripting binding, V098 procedure or V099 enforcement. Their existing
deployment authorization is not permission to add this probe silently.

Read-only synthetic SELECTs can validate PARSE_JSON conversion and canonical
join results. Read-only metadata plus dated, sanitized protected-run receipts
can show deployment/role/source evidence without replaying mutations. A reviewed
historical behavioral receipt with actual workload, role and outcome may satisfy
the missing proof without new writes; workflow head alone, grant text, migration
ledger presence or EXPLAIN alone cannot. Preserve UNKNOWN when that chain is
missing. A DEV temporary write is optional additional engine evidence, not a
prerequisite to complete the offline collector engineering or deploy PR568.

Parent handoff: add only the highlighted temporary-engine decision to the owner
Word checklist; retain absent connection/warehouse and full PROD behavioral
evidence as separate blockers. Do not send the approval question directly to the
user from this worktree or close DATA376 on the strength of this proposal.
