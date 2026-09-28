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

V106–V108 have DEV runtime/persistence proof from PR #502. V109 has attributable DEV review proof here. V110 and V113 have live handoff proof here. V111 and V112 live view reads are recorded below. The set remains outside PROD readiness pending downstream failure/retry proof, complete controlled negative fixtures, and protected production promotion review.

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

## Residual acceptance limits

No current, safe DEV fixture or hook faults the handoff procedure after downstream investigation intake begins and before commit. An earlier validation error or lock timeout would not prove that rollback boundary. `RETRYABLE_FAILURE` and `TERMINAL_FAILURE` are client classifications in the current contract, not durable failed receipts from a rolled-back transaction; their live distinction still requires a controlled downstream fault or application-side transport fixture. Missing/invalid evidence, stale snapshot linkage, already-governed, exact duplicate/mirror, and controlled-access outcomes have contract/unit coverage but no newly executed live DEV fixture in this pass. Source approval, ingestion, and publication remain outside role grants and the handoff procedure's DML path; representative approval, ingestion, and publication calls/DML were denied live. Data #450 and PR #503 therefore remain open/draft.

## V106–V113 protected promotion reassessment

All eight DEV migration ledger checksums match the source-controlled migration plan. ADR 0041 approves the three-role design in PR #503; this does not constitute approval to promote any migration to PROD.

| Migration | DEV deployed | DEV acceptance proven | Governance approved | PROD-ready | Remaining blocker |
| --- | --- | --- | --- | --- | --- |
| V106 | Yes | Schema, bounded view, identity and persistence assertions in #449; live review/handoff linked here | Architecture accepted; promotion pending | No | Protected PROD review of schema and grants |
| V107 | Yes | Runtime create/outcome/finalize and service-boundary proof in #449 | Architecture accepted; promotion pending | No | Protected PROD role and procedure review |
| V108 | Yes | Typed recommendation commit, replay, concurrency, and rollback evidence in PR #502 | Architecture accepted; promotion pending | No | Protected PROD transaction review |
| V109 | Yes | Attributable human review, persisted event, runtime denial, and stale/rejected state denials here | ADR 0041 accepted in PR; promotion pending | No | Protected PROD reviewer assignment and caller-attribution proof |
| V110 | Yes | First intake, receipt, exact retry, conflicting replay, and independent-session concurrency here | ADR 0041 accepted in PR; promotion pending | No | Post-intake failure/retry and controlled negative fixtures |
| V111 | Yes | Live alternate-distribution identity link for retained shadow observation; contract tests | Contract reviewed in branch; promotion pending | No | PROD catalog/identity snapshot and access review |
| V112 | Yes | Live artifact metadata match; absent prior assessment remained absent; contract tests | Contract reviewed in branch; promotion pending | No | PROD artifact and assessment snapshot/access review |
| V113 | Yes | Live snapshot-matched handoff and negative stale identity/state paths; contract tests | ADR 0041 accepted in PR; promotion pending | No | Explicit invalid-evidence/snapshot DEV fixture and post-intake failure proof |

The set is **not PROD-ready**. The remaining DEV proof is bounded to the post-intake fault/retry and missing identity/evidence/source-state fixtures; PROD still needs its own protected approval and equivalent security checks. API PR #112 remains parked through V106–V113 approval, sequential V123/V124 promotion, PROD metadata view creation, and `OH_LYME_PROD_READ` verification.
