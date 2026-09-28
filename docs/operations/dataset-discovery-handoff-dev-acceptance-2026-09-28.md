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

This run proves first handoff, exact retry/lost-response recovery and conflicting event replay against a live recommendation. A simultaneous two-session handoff was attempted but one local Snowflake CLI process failed before connecting due to its installation lock; genuine same-handoff concurrency is **not yet proven**. A downstream failure/retry fault has not been injected. The runtime cannot yet SELECT the bounded handoff receipt view; V125 adds only that DEV grant and must pass the protected migration ledger before live status-read proof. No PROD role/grant or V106–V113 promotion is authorized by this DEV exercise.

V106–V108 have DEV runtime/persistence proof from PR #502. V109 has attributable DEV review proof here. V110 and V113 have live handoff proof here, with concurrency and fault injection still open. V111 and V112 are applied and have repository contract tests, but their individual live acceptance assertions need review before PROD readiness. V106–V113 as a set are not PROD-ready until the remaining DEV security/negative tests, protected status-read migration, and independent production promotion review pass.
