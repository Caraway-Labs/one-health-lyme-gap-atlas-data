# Data #450 controlled DEV handoff acceptance, 2026-09-28

This is an acceptance exercise against a genuine hosted shadow recommendation and retained catalog observations. It is not a public-health conclusion, source approval, acquisition, ingestion, or publication. PROD was untouched.

## Identity and input

- DEV reviewer connection: individually authenticated `MATTHEWCARAWAY`, role `OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER`; `CURRENT_USER`, `CURRENT_ROLE`, `CURRENT_DATABASE`, and `CURRENT_WAREHOUSE` were checked before mutation.
- DEV runtime connection: `OH_LYME_DEV_DATASET_DISCOVERY_SVC`, role `OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME`; the same context fields were checked.
- Recommendation `3686d9c8ae1e230698613fdcc24d2f2ffabee064df6bfd0ce80fb3bdc8894d02`, version `1f04868f1a06df60b99179faced37aed16ccc66d71eda035c70c9d2c52da2c45`, hosted shadow run `dd-shadow-078c025512144f61b84b3ef8d28816df`.
- Canonical resource `candidate:afdb1f0d5c1cedfe97f99b0d5e7448f6`; catalog dataset `4321e7f1e6c0251e7a12384e35751c604e788803911f4ce155ef14ed8ec1b5ef`, resource `9d545c79fff0a7c51cb7f4ce0c0910489581cc76ab0fdc3fdfbc7a0558f5dd6c`, observation `84564275a83cc8f5ebc716f3c175b834afde314adfa28ce9c7baae5448a8e9dd`.
- The candidate was classified `ALTERNATE_DISTRIBUTION`, with `RIGHTS_REVIEW_REQUIRED`. Its observed title, description, publisher, spatial coverage, modified date and access level were tied to the retained observation. License and detailed variable schema remain unknown. The review rationale required rights, distribution lineage, geography and sample assessment before any approval.

## Result

`SP_APPEND_REVIEW_EVENT` returned review event `7509aa88fcdf9c2e8debbaa7bb708f581d1bc5d8147c77c13d6935d365ec6d25`, sequence 85, `PENDING` to `ACCEPTED_FOR_INVESTIGATION`, with the authenticated reviewer identity. `SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION` returned handoff `221475cb016e1c377381effe0f3ffbefa9baa04b4fb96ddf3babf1b9a8cab4c2`, operation key `handoff-v1:<recommendation_version_id>`, disposition `HANDED_OFF`, investigation status `PENDING`, relationship `ALTERNATE_DISTRIBUTION`, and `INVESTIGATE_BEFORE_ACQUISITION`. The bounded handoff receipt view returned exactly one row for this version.

An exact retry returned the same handoff ID and logical result. Reuse of the same version with a changed review event failed `CONFLICTING_HANDOFF_REPLAY`. Runtime calls to both human procedures failed at the privilege boundary. Reviewer-only reads and procedure calls did not grant base-table DML. The handoff procedure inserts only `GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS`; it does not call source approval, ingestion or publication procedures.

## Remaining proof and promotion gate

This run proves first handoff, exact retry/lost-response recovery and conflicting event replay against a live recommendation. The initial simultaneous CLI attempt failed before one process connected; the independent-connector rerun below resolves that gap. No PROD role/grant or V106–V113 promotion is authorized by this DEV exercise.

V106–V108 have DEV runtime/persistence proof from PR #502. V109 has attributable DEV review proof here. V110 and V113 have live handoff proof here. V111 and V112 live view reads are recorded below. The subsequent post-intake rollback exercise and owner-reviewed contract substitutions are recorded below. Protected production promotion review remains separate.

## Protected V125 deployment and status read

The protected [DEV workflow run 36479147267](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/36479147267) passed Quality, dbt parse, container build, and the protected migration step at commit `382f0ba9202b99c2310ce10c855d59a1b57c25ff`. It applied only V125. The DEV `GOVERNANCE.SCHEMA_MIGRATIONS` receipt records V125, `V125__dev_dataset_discovery_runtime_handoff_receipts.sql`, SHA-256 `bb3d0838168f8924a81fcf2c4c8aa3b6192b00356743db8d3e98012e1f83b8b6`, applied 2026-09-28 13:27:36 -07:00. This matches the local migration plan. V125 is excluded from the PROD plan.

The authenticated runtime role then selected handoff `221475cb016e1c377381effe0f3ffbefa9baa04b4fb96ddf3babf1b9a8cab4c2` from `DATASET_DISCOVERY.V_HANDOFF_RECEIPTS` and saw `HANDED_OFF` / `PENDING`. A direct read of `GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS` and direct UPDATE of that table were denied. The runtime gained only bounded status visibility.

## Independent-session concurrent delivery

The controlled Data #449 fixture version `9af96882e2a28fdc46aad5a37a158add46e7c90752a7bdfdaf9b6d8129f3f90a` was separately accepted for investigation by the authenticated reviewer, producing review event `55dc3ff6d70a0175307f79b3899c26bcbe10f3f5e4ca91708b532e29e67ffe56`. This is labeled acceptance data, not an agent suitability conclusion. `scripts/verify_dataset_discovery_handoff_concurrency_dev.py` opened two separate Snowflake connector sessions (`28197005770895878`, `28197005770880566`), synchronized calls at a barrier, and received the same handoff `62146938de1ce8e41a6537a8fa81d1cad5926471030e2ec5f589b35568213005` in query IDs `01c7614b-020b-b9a3-0064-2d0701026afe` and `01c7614b-020b-b9a3-0064-2d0701026b02`. The bounded view counted one row and one distinct handoff ID. No duplicate investigation request was exposed; both calls use the same downstream ledger row.

## Negative and role evidence

`scripts/verify_dataset_discovery_handoff_negative_dev.py` used the distinct human reviewer and service PAT sessions. Denied cases and query IDs from the final run: never accepted `01c76151-020b-bbf1-0064-2d070103233a`; rejected fixture `01c76152-020b-b9a3-0064-2d0701026bf2`; stale event `01c76152-020b-b9c8-0064-2d070103798a`; missing event `01c76152-020b-b9c8-0064-2d07010379aa`; unknown version `01c76152-020b-bbf1-0064-2d070103235e`; reviewer direct review-table read `01c76152-020b-bbf1-0064-2d0701032382`; source-approval call `01c76152-020b-b9c8-0064-2d07010379ae`; reviewer ingestion-run DELETE `01c76152-020b-b9a3-0064-2d0701026c16`; reviewer publication UPDATE `01c76152-020b-b9c8-0064-2d07010379b2`; runtime authoritative table read `01c76152-020b-bbf1-0064-2d0701032386`; handoff-table UPDATE `01c76152-020b-b9c8-0064-2d07010379b6`; source-version UPDATE `01c76152-020b-b9a3-0064-2d0701026c1e`; ingestion-run DELETE `01c76152-020b-bbf1-0064-2d070103238a`; publication UPDATE `01c76152-020b-b9a3-0064-2d0701026c22`. The DML probes used `WHERE 1=0` and were denied before any mutation. Earlier runtime review/handoff procedure denials also remain valid.

The persisted review history row for the hosted shadow recommendation records reviewer `MATTHEWCARAWAY`, exact reviewer role, prior `PENDING`, new `ACCEPTED_FOR_INVESTIGATION`, event 85, rationale, conditions, and `2026-09-28 13:05:38 -07:00`. The identity is not the service account, procedure owner, or migration identity.

Account grant inspection found runtime held only four recommendation-write procedure USAGE grants and bounded view SELECTs, including the new handoff receipt view. Reviewer held only review/handoff procedure USAGE and five bounded view SELECTs. WRITE_OWNER held ownership of those six bounded procedures, `READ SESSION` on account, and their enumerated table/view dependencies; it has no source approval, ingestion, or publication grant. Runtime is assigned only to the service user; REVIEWER only to `MATTHEWCARAWAY`; WRITE_OWNER only to `OH_LYME_DEV_MIGRATION_DEPLOYER`, not a login user.

V111's runtime view returned `ALTERNATE_DISTRIBUTION` / `SAME_CATALOG_DATASET` for the hosted shadow candidate and its linked resource. V112's artifact view returned the same retained observation and artifact hash; the prior-assessment view returned zero rows for this candidate, preserving absence rather than manufacturing a score. Both views were readable with the bounded runtime role.

## Post-intake rollback and retry

Protected [DEV workflow run 36482497080](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/36482497080) executed `scripts/verify_dataset_discovery_handoff_fault_dev.py` with the DEV migration-deployer identity. The temporary branch-gated workflow call was removed after the run; no fault input or production-callable switch remains. The script uses the V113 serialization key and actual investigation-request table, within an explicit transaction. It is a transaction-shape probe, not a fault injected into the deployed V113 JavaScript procedure.

The controlled fixture version `b0d664168a3ec74d143958e9456f15d58c3947b48d1cfc9931ee494e12133d57` was accepted by the authenticated human reviewer under event `5ca401592d3b6566d38e0427d9c3331fc735109c337050cf4242039c79954095` (sequence 92). The probe observed one uncommitted investigation row, one bounded receipt row, and one queue row, then raised `DATA450_AFTER_INTAKE_INSERT_BEFORE_COMMIT`. After rollback all three counts were zero. The real handoff procedure then accepted the same version/event and returned handoff `5371dd2ea06de1030b73d01e963067ff8ceb30b4798fb5d74fb57b4a424f603c`, `HANDED_OFF` / `PENDING`. Its exact replay returned the same ID; the bounded receipt view contained one logical row. The failed transaction left no durable failed receipt or duplicate idempotency state. No approval, ingestion, publication, or catalog state was touched.

`RETRYABLE_FAILURE` and `TERMINAL_FAILURE` are client-side classifications, not persisted procedure rows. The Dataset Discovery handoff client owns this classification: an acknowledgement loss, transport interruption, or transient database availability error is retryable with the **same version and review-event IDs**; a validation, stale state, authorization, policy, or conflicting-replay error is terminal until its underlying governed state is corrected. The caller may read the bounded receipt and retry after an unknown outcome. V113 serializes on `WRITE_SERIALIZATION` and derives `handoff-v1:<version>`; an exact replay returns the committed result and changed logical content fails closed. Application-side transport classification belongs to Dataset Discovery #3 and is outside Data #450 acceptance.

## Controlled source-state assessment

The retained DEV snapshot has 10 `EXACT_DUPLICATE` V111 identity links and 968 `ALTERNATE_DISTRIBUTION` links. V111 does not infer `MIRROR`; contract tests explicitly forbid inventing it. The exact duplicate candidate `candidate:55f7f2e13d5b598d390c0caed44b62e9` has `EXACT_RESOURCE_KEY` basis. The typed Dataset Discovery `RecommendationWrite` rejected it as an abstaining candidate before recommendation persistence: `Value error, abstaining candidate cannot be persisted as a recommendation`. The controlled run `data450-exact_duplicate-22dabdb180174692ad0397e9d9425a06` was finalized as `SUCCEEDED_NO_NEW_CANDIDATES` (zero processed, zero recommendations). Thus exact duplicate prevention is live proven upstream; an accepted duplicate handoff is not a valid reachable fixture through the current client.

The controlled-access resource `candidate:d1ff6c4a9f6f1c9e91d50ab9fa507a11` was persisted via the typed runtime adapter as recommendation `60dc164aed0617fd3cc3b4404f6ce9692fe987b4cf61a636b6e7dd5dc4077f20`, version `c1b12f6681edda4f247037beedaa6e3f1b29a90c258630e4512ce1c6cfd35016`, run `data450-controlled_access-a6737ca76a2942a081e3987696ded1ad`. Human event `3414a72571c66c98a4f815dd5dc604bc7fa70969560eb1ac5b97dde6b847597c` accepted it for investigation with explicit rights/access conditions. The real handoff returned `03310fbbb4725bdff2ae6875c0d9735362bfdd3fff36d0a84a68aa740f72b4d1`, `HANDED_OFF` / `PENDING`, acquisition boundary `NO_AUTOMATED_ACQUISITION`. This is investigation intake, not a `blocked_by_rights` policy finding or access authorization. The retained observation `cfb30c9ca8b52c98658a6c28fdced0cea666d2dbc3ef57f6c5d7b59a0917d9e4` and catalog dataset/resource IDs remained linked; no source approval, acquisition, ingestion, or publication followed.

Five resources in `V_CANDIDATE_GOVERNED_STATUS` are already governed, but none joins the current `V_CANDIDATE_SUMMARY` snapshot. There is no existing legitimate candidate from which to create an accepted already-governed handoff without new catalog/governance data. No such data was manufactured. Likewise, no accepted recommendation with absent evidence or stale evidence snapshot can be produced through the current bounded runtime/review interfaces without bypassing the protected persistence checks or altering authoritative observations. V113 contains `MISSING_EVIDENCE` and `EVIDENCE_CATALOG_MISMATCH` guards, with contract tests, but those branches remain without live DEV handoff proof. A random nonexistent ID would exercise `REJECTED_OR_STALE_HANDOFF`, not the intended evidence/snapshot branch.

## Owner-reviewed acceptance substitutions

The Data #450 owner accepts contract-test coverage for deliberately missing/invalid evidence and stale snapshot linkage because the reviewed runtime and human-review interfaces cannot legitimately create an accepted recommendation with those defects. Creating one would bypass governance or alter authoritative catalog observations. `tests/test_dataset_discovery_handoff_snapshot_contract.py::test_missing_or_foreign_evidence_fails_before_investigation_intake` asserts the `MISSING_EVIDENCE`, `AMBIGUOUS_EVIDENCE`, and `EVIDENCE_CATALOG_MISMATCH` guards precede intake and bind the canonical catalog identity. `test_stale_snapshot_fails_before_investigation_intake` asserts the pinned `ingestion_run_id` match, mismatch denial before intake, and rollback path. These are **CONTRACT TEST ACCEPTED**, not live DEV executions of corrupt state.

The owner also accepts **CONTRACT TEST ACCEPTED** for `ALREADY_GOVERNED`, given the absence of a safe natural DEV candidate/governed-source overlap. `tests/test_dataset_discovery_handoff_contract.py::test_already_governed_reuses_authoritative_resource_identity_without_onboarding` asserts V106 derives governed status from the existing `DATA_SOURCE_VERSIONS` record by canonical resource key, V113 returns `ALREADY_GOVERNED` rather than a pending investigation, carries the original catalog identity, and contains no approval/ingestion-table write. `test_handoff_has_no_approval_or_ingestion_write_path` checks the bounded insert and forbidden DML. V113's serialized operation key and replay path prevent a duplicate logical receipt. No catalog or governance data was manufactured.

`EXACT_DUPLICATE` is **LIVE PROVEN upstream** by V111's link and the typed client's abstention before recommendation persistence; forcing a handoff would violate that contract. `MIRROR` is **NOT APPLICABLE** because V111 does not assert it. `RETRYABLE_FAILURE` / `TERMINAL_FAILURE` transport and database-error classification is **DOWNSTREAM APPLICATION OWNERSHIP** under Dataset Discovery #3's handoff client; it is not a Data #450 durable Snowflake row or closure condition. Data #450 owns atomic intake, rollback, stable receipts, idempotency, security, and status persistence, all proven above.

Under these owner decisions, the Data #450 definition of done is satisfied in DEV. No known Data-layer acceptance blocker remains. This does not approve or execute PROD promotion.

## Negative acceptance matrix

| Case | Status | Evidence / limit |
| --- | --- | --- |
| Never accepted | LIVE PROVEN | Reviewer handoff denied |
| Rejected | LIVE PROVEN | Rejected review handoff denied |
| Stale review | LIVE PROVEN | Prior event rejected |
| Missing review | LIVE PROVEN | Missing event rejected |
| Invalid/missing evidence | CONTRACT TEST ONLY; OWNER ACCEPTED | V113 evidence guards; exact tests above |
| Stale snapshot | CONTRACT TEST ONLY; OWNER ACCEPTED | V113 pinned snapshot join; exact test above |
| Unknown version | LIVE PROVEN | Unknown version denied |
| Already governed | CONTRACT TEST ONLY; OWNER ACCEPTED | V106 authoritative status and V113 disposition; exact test above |
| Exact duplicate | LIVE PROVEN | V111 link and typed client abstention; handoff not reachable |
| Mirror | NOT APPLICABLE | V111 does not assert MIRROR; alternate distribution is distinct |
| Alternate distribution | LIVE PROVEN | Hosted shadow recommendation and handoff preserve relationship |
| Controlled access | LIVE PROVEN | Intake with `NO_AUTOMATED_ACQUISITION` |
| Runtime review attempt | LIVE PROVEN | Procedure privilege denied |
| Runtime handoff attempt | LIVE PROVEN | Procedure privilege denied |
| Direct governance write | LIVE PROVEN | Runtime and reviewer DML denied |
| Source approval | LIVE PROVEN | Reviewer procedure attempt denied; no handoff DML |
| Ingestion | LIVE PROVEN | Ingestion-run DML denied; no handoff DML |
| Publication | LIVE PROVEN | Publication DML denied; no handoff DML |

V111 live acceptance confirms a canonical identity link with retained basis for exact duplicate and alternate distribution, and no parallel identity namespace. Mirror is not a supported assertion today. V112 live acceptance confirms bounded artifact metadata and observation hash, absence of a prior assessment where none exists, and controlled-access context via the linked resource; no private artifact bytes were exposed to runtime. Both are sufficiently proven in DEV for a PROD promotion **review**, subject to the protected target snapshot/grant review, but neither is approved for PROD application yet.

## V106–V113 protected promotion reassessment

All eight DEV migration ledger checksums match the source-controlled migration plan. ADR 0041 approves the three-role design in PR #503; this does not constitute approval to promote any migration to PROD.

| Migration | DEV deployed | DEV evidence complete | Governance accepted | Security evidence sufficient | Ready for PROD promotion review | Review focus |
| --- | --- | --- | --- | --- | --- | --- |
| V106 | Yes | Yes; #449 schema/persistence round trip | Yes; #449 scope | Yes; bounded grants | Yes | Target schema and grants |
| V107 | Yes | Yes; #449 runtime create/outcome/finalize | Yes; #449 scope | Yes; service boundary | Yes | Target role/procedure grants |
| V108 | Yes | Yes; PR #502 typed commit, replay, concurrency, rollback | Yes; #449 scope | Yes; runtime-only write procedure | Yes | Target transaction behavior |
| V109 | Yes | Yes; attributable review and state denials | Yes; ADR 0041 | Yes; runtime review denied, reviewer scoped | Yes | Target reviewer assignment and caller proof |
| V110 | Yes | Yes; handoff, replay, concurrency, post-intake rollback; owner-accepted already-governed contract test | Yes; ADR 0041 | Yes; no approval/ingestion/publication path | Yes | Target handoff and grants |
| V111 | Yes | Yes; canonical alternate and exact-duplicate links | Yes; reviewed contract | Yes; bounded runtime view | Yes | Target identity snapshot and access |
| V112 | Yes | Yes; artifact hash, absent assessment, controlled access context | Yes; reviewed contract | Yes; bounded runtime view | Yes | Target artifact/assessment access |
| V113 | Yes | Yes; valid handoff, rollback/retry, owner-accepted evidence/snapshot contract tests | Yes; ADR 0041 | Yes; stale review/runtime denial | Yes | Target snapshot guards and rollback |

The owner-reviewed substitutions complete Data #450 DEV acceptance. All V106–V113 migrations are **ready for protected PROD promotion review**, but are neither approved for PROD deployment nor PROD deployed. The promotion review must inspect target-state roles, catalog/identity snapshots, migration plans and security controls before authorization. API PR #112 remains parked through V106–V113 approval and promotion, sequential V123/V124 promotion, PROD metadata view creation, and `OH_LYME_PROD_READ` verification.
