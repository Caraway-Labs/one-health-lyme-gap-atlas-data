# Data 698 / 702 / 703 human review package

Status: FIXTURE IMPLEMENTATION COMPLETE; installed DEV execution and authoritative lineage
BLOCKED. No scientific/Data approval is requested from or recorded by automation.
PR #706 must remain draft. Source baseline is
`6f2195e8d876a6e3093d872214a2254440e6a040`; final implementation commit and CI
are recorded in the PR review request. No PROD object, grant, row or pointer was
changed. No migration was installed in live DEV.

## Approved designs and remaining execution boundary

The Product Owner approved Decision 1 (fixed fixture deployment design/test scope)
and Decision 2 (restricted retained-lineage diagnostic design). Do not request
those design decisions again. Neither approval substitutes for independent
exact-head engineering/security review or exact-action PROD DDL authorization.

The dedicated `release_integrity_fixture` job in `deploy-dev.yml` now implements
the fixture mechanism. It binds the exact PR head, successful final-head Quality
check, configured human engineering/security APPROVED reviews, immutable image
revision/digest, original/rendered migration checksums and synthetic marker.
Only V157/V158 are selected. A separate ledger and schema binding permit exact
replay and interrupted-V157 recovery; mismatched attempts fail closed.

Before dispatch, provision `RI706_REVIEW_POLICY` with authorized engineering and
security reviewer login lists. The author and automation cannot satisfy this gate.
Provision `RI706_OWNER_USER`, `RI706_PUBLISHER_USER`, `RI706_READER_USER` as DEV
environment variables and corresponding `RI706_*_PRIVATE_KEY_B64` secrets
(full PEM encoded as base64; optional matching passphrase secrets). These must be
separate approved service identities with the fixed DEV roles, not personal keys.
The existing protected migration/runtime identities are reused only in workflow.
Those new policy/profile entries are currently absent. No dispatch was attempted.

Use `ri706-fixture-execution-artifacts.json` as the exact workflow artifact input
and the explicit `RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL` marker.
The protected job builds/reuses only its reviewed image, assembles the pinned ML
handoff, checks review again, injects a planned V157 interruption and resumes the
same image through the acceptance matrix. It retains redacted query-ID receipts.
No App Platform deployment or generic migration command is used.

Engineering/security: review ADR0047 and the approved fixed fixture schema mapping
`FEATURE_STORE -> RI706_FEATURE_STORE`, `PRESENTATION -> RI706_PRESENTATION`,
`GOVERNANCE -> RI706_GOVERNANCE`, all within
`ONE_HEALTH_LYME_GAP_ATLAS_DEV`. The two offline-rendered DDL files and source/
rendered checksums are in `release-integrity-dev-fixture-proposal-2026-10-18/`.
These files are not migration receipts and must not be run manually.

The implemented bounded fixture-only mode in the existing `deploy-dev.yml` uses
exact reviewed SHA, both original source hashes, fixed schema mapping, full
observed pending inventory and immutable image digest. The mode must reject
existing fixture schemas (unless a separately verified exact-attempt recovery),
PROD context, arbitrary schemas, unrelated DDL and live DEV pointer/ledger writes.
It must use a separate fixture ledger and preserve all live DEV migration history.
Independent exact-head review of this implementation remains required before
privileged execution. Local tests are not installed Snowflake acceptance.

Current scope guard: `apply_migrations(release_integrity_only=True)` rejects
DEV. `apply-reviewed-dev-migrations` instead reconciles legacy history and
applies the full pending set: V155, V157, V158. V155 is not part of this task's
scoped authorization. Do not dispatch that generic operation as a shortcut.
The existing `dev` GitHub environment has no required-reviewer/branch restriction;
this is an application-scope/security-review boundary, not a pending GitHub
reviewer approval. Credential values were not accessed/exported.

Required executor: protected `OH_LYME_DEV_MIGRATION_DEPLOY_SVC`, primary role
`OH_LYME_DEV_MIGRATION_DEPLOYER`, database suffixed DEV, warehouse
`OH_LYME_DEV_INGEST_XS_WH`. Existing GitHub DEV key-pair secrets are configured;
use them only inside the reviewed workflow. Do not export them to a personal PAT.

Fixture security scope requiring explicit review:

| Identity/role | Allowed fixture surface | Required negative checks |
| --- | --- | --- |
| Migration deployer | Create/own only three fixture schemas and dependencies; install exact pair; fixture ledger | Live DEV/PROD unchanged; unrelated DDL not selected |
| DEV OWNER | Only fixture owner-control procedure calls for expressly labelled synthetic tests | No actual scientific/Data decision; no live control calls |
| DEV ML_PUBLISHER | Fixture staging/publish procedure USAGE only | Base-table DML, compatibility admission, authorization and rollback denied |
| DEV READ | Fixture presentation SELECT only | Base tables, writes and all publisher/owner procedures denied |
| DEV RUNTIME | Existing runtime surface, no new owner control | No compatibility/publication approval authority or inherited OWNER |

Fixture prerequisites must be separately installed in the three fixture schemas:
canonical3,144county identity set; original and target synthetic retained releases;
source metadata/manifests and observations for all five model sources; current
release/atlas projections; fixture V158 ledger commit. Preserve the real frozen
ML138 file bytes and input identities. Synthetic source rows cannot prove live
scientific compatibility. Calls producing fixture-only test decisions require
explicit fixture scope and must be marked SYNTHETIC_TEST_NOT_APPROVAL, never
represented as a human Data/scientific sign-off. Real admissions remain human.

## DEV execution and recovery acceptance matrix

Every case must retain exact SHA/image/source and rendered migration hashes,
connection context, Snowflake query IDs/results, pre/post snapshots and outcome.
No image was executed in isolated DEV yet; plan image/receipt fields are null.

| Gate | Required execution / retained evidence | Current status |
| --- | --- | --- |
| Install/replay | V157/V158 in fixture ledger only; same-SHA retry; reject changed checksum/commit; V155 and live ledgers/pointers unchanged | BLOCKED |
| Owner dependencies | Actual procedure owner reads only scoped prerequisites; validate grants and primary/secondary roles | BLOCKED |
| Tier1 compatibility | Exact and admitted pairs; changed value, source version/run/artifact/hash, field map, row hash, membership and wrong bundle rejected | BLOCKED |
| Duplicate/concurrency | Identical decision replay once; changed replay fails; two sessions serialize; distinct admissions never multiply outputs | BLOCKED |
| Staging | No authority denied; identical chunk retry stable; changed chunk rejected; eight-attempt cap; partial attempts retained | BLOCKED |
| Both frozen fits | Exact county SHA, two3,144row fits, probability sums/order, primary[801,35,112,2196], secondary[1325,1687,97,35], AK/HI35Unknown | Offline PASS; installed BLOCKED |
| Atomic publication | Missing fixture geography forces failure after assignment insertion; no batch/pointer/event partial commit; staged evidence remains | BLOCKED |
| Activation/replay | Exact/admitted target works; incompatible/wrong release denied; publication replay does not reactivate withdrawn batch | BLOCKED |
| Rollback | Deactivate/reactivate via fixture owner control; events append; assignments immutable; release rollback uses admitted expectations | BLOCKED |
| Permissions | Actual allowed/denied SQL under each service role, not just SHOW GRANTS; deny inherited owner/publisher authority to readers | BLOCKED |
| Complete inventory | All10datasets/models plus15reader views and five independent consumers; missing artifact/metadata and same-count substitutions fail | Offline PASS; installed BLOCKED |
| Recovery | Inject partial migration/publication failure; exact attempt recovery; retain failed staging/history and no unrelated cleanup | BLOCKED |

Read-only Snowflake fixtures from the prior exact migration sources cover21
eligibility SELECTs, including duplicate/zero/activation selection. These remain
useful compilation evidence, not substitutes for this installed matrix.

## Full lineage: exact access boundary and minimum grants

Fresh named PAT contexts verified: MATTHEWCARAWAY / OH_LYME_DEV_READ / DEV /
OH_LYME_DEV_INGEST_XS_WH and MATTHEWCARAWAY / OH_LYME_PROD_READ / PROD /
COMPUTE_WH. See `release-integrity-access-preflight-2026-10-18.json` for query IDs.

No new role is missing: `OH_LYME_PROD_READ` exists and can select the V137/V148
`LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V`. It cannot SELECT:

- `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_RELEASES`
- `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_DATA_SOURCES`
- `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_OBSERVATIONS`
- `ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_COUNTY_ATLAS`

Do not grant READ broad base-table SELECT. Proposed minimum surface is SELECT
on four secure views in existing LINEAGE_AUDIT, scoped to the two exact retained
release/bundle pairs and five model sources: `RETAINED_MODEL_RELEASES_V`,
`RETAINED_MODEL_SOURCES_V`, `RETAINED_MODEL_MEMBERSHIP_V`,
`RETAINED_MODEL_OBSERVATIONS_V`. Existing database/schema USAGE and audit-view
SELECT suffice otherwise. Review-only definitions/grants are in
`sql/validation/release-integrity-retained-diagnostic-proposal.sql`.
The migration/view owner needs its existing dependency SELECT on the four base
tables and CREATE VIEW/ownership in LINEAGE_AUDIT; verify that under the protected
identity rather than granting an elevated role to the diagnostic caller.
No role membership, INSERT/UPDATE/DELETE, raw payload/artifact URI or approval
procedure privilege is required. The exact-action request JSON pins both SQL
hashes, dependencies, four SELECT grants and revocation script. Proposed views
expire closed at 2026-10-25T00:00:00Z; delayed review requires renewed hashes and
authorization. Revoke/drop only these four views after receipt acceptance.

Installing these PROD audit views/grants is itself a **separate protected PROD
DDL authorization**, expressly not granted by this task. Alternatively, an already
authorized protected read-only diagnostic may return exactly this scoped evidence
without adding reader grants; it still requires explicit identity/action scope.
Never use OWNER, MIGRATOR or ACCOUNTADMIN as a routine lineage-read workaround.

Once authorized/provisioned, run the named READ verifier with
`--reviewed-projections`. It checks both exact bundles, actual canonical county
membership, complete source versions/runs/artifacts/checksums/attribution/maps,
and every observation's governed lineage with multiplicity in state partitions.
Audit/base row counts must match. Timeout60seconds per statement; partial receipts
are not success. Source mismatches now record source/key/field and exact values;
row mismatches record state and directional multiplicities without county records.

Current full-lineage result: **BLOCKED, no authoritative mismatch conclusion**.
Tier1 scientific carry-forward eligibility: **UNDETERMINED**, not approved.
The18,864matching predictor cells do not change that result. Both LCA variants
retain their frozen October15input pair; source compatibility for later releases
requires its own complete comparison and human decision.

## Eventual protected PROD actions (none authorized now)

After installed DEV gates and full lineage pass, request scientific, Data,
engineering and access-control re-review against the exact latest commit.
The authenticated GitHub account is the PR author, so do not fabricate a native
self-approval; a PR comment requests human review instead of inventing a reviewer.

Later, separately authorize: merge; build and verify the same DEV-tested immutable
image digest; protected V157/V158 installation with exact pending/source hashes;
owner Tier1 compatibility decision (only if proof supports it); Data publication
authorization; frozen ML batch staging/publication; full completeness admission;
protected semantic publish/rollback and real service canary; any API/Web cutover.
Provision `ATLAS_API_CANARY_PRIVATE_KEY_PEM_B64` and optional passphrase in the
protected production environment; those secret names are currently absent.
Verify OH_LYME_API_SVC/OH_LYME_PROD_READ actual least-privilege live access.
A CI image or human READ-role result is not a DEV-tested image or service proof.
