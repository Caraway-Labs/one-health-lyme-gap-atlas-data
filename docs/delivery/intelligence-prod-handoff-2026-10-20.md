# Intelligence production delivery: reconciliation and owner handoff

As of October 20, 2026 (America/Denver). Main reviewed:
`54104ef27691fc0811a665470d647e03459dbf29` (approved PR #714 merge).

Work was isolated in new `intelligence-714-review-20261020` and
`intelligence-667-reconcile-20261020` worktrees. Existing branches/checkouts were
not reset or edited. PR updates are engineering work, not production approval.
PR #714 alone was merged after explicit owner approval of its exact head. No
production workflow or data operation was executed. PR #667 remains unmerged.

## Completed technical work

- PR #714 was freshly reviewed at `06eb1df`, with one P2 finding resolved at
  `f60d04391201dc8c6e8b028f4bee928962a178c6`: the synthetic checkpoint probe now
  requires valid nonempty base64 raw content and the expected artifact hash,
  rather than accepting a lease-marker-only row. It returns counts only; actual
  content SHA verification belongs to the authorized creation receipt.
- PR #714 was merged at the explicitly approved
  `f60d04391201dc8c6e8b028f4bee928962a178c6`, producing main merge commit
  `54104ef27691fc0811a665470d647e03459dbf29`. Exact-head
  [Quality 39519628895](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/39519628895)
  passed **4,793 tests / 3 skipped**, lint/format, mypy, dbt, container/package,
  offline dry-run and secret checks. Deployment was skipped. Focused local
  checks passed **51 tests**; a named-PAT, SELECT-only DEV constant probe checked
  valid/empty/invalid/missing base64 behavior without accessing source payloads.
- PR #667 incorporates reviewed main without rewriting its earlier commits.
  The conflicting production workflow keeps both `checks: read` and
  `actions: read`, main's January warehouse/session settings, V153 receipt gate,
  fixed run identity, 31/301-minute recovery/acquisition limits and underlying
  process timeouts, NLCD's five-minute limit, and generic source-version/decision
  checks. The exact EID-only request guard and six-minute EID limit are retained.
- Existing EID registration, metadata policy, adapter, lease/claim storage,
  migrations, state machine and approval/handoff controls are reused. The EID
  test now supplies `run_id=None` to the updated CLI signature. New offline Bash
  tests execute the actual dispatch guard with stubs and reject unreviewed refs,
  resume, retained run IDs, alternate source/decision IDs and missing green CI.
- No source approval, public payload, migration, role or architecture was changed.
  Merge-carried main migrations remain byte-for-byte main; inherited whitespace
  in historical files was not normalized or repaired.

Exact-head focused/full validation for the reconciled PR is recorded in PR #667.
GitHub protection inspection found strict successful `checks` required and admin
enforcement enabled, but `required_pull_request_reviews=null`. This does not
override the owner's explicit merge-approval boundary. The technical review's
COMMENTED submission is not an independent account's APPROVE.

## Source and evidence boundaries

Use only `cdc-eid-expedited`, registry v1, source SHA256
`51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4`, with
`DATA-132-135-EID-ADMISSION-2026-10-09`. Endpoint:
`https://wwwnc.cdc.gov/eid/rss/expedited.xml`. This is the separately approved
metadata-only EID pilot; it is not CDC Newsroom, Vital Signs, or completion of
DATA #132's three-of-five-feed DEV acceptance. Keep #132/#135/#680 open until
their own criteria are actually met.

Publish only the permitted metadata, source attribution, original free link,
publisher date states/language and required nonendorsement/limitations. No
descriptions, article text, public excerpts, image values/bytes, logos or inferred
geography/disease claims are enabled. Registration and acquisition stay separate.

The earlier live audit reported zero V2 rows, zero registry rows and no synthetic
retention pair. Those observations were **not re-run or upgraded to current live
acceptance in this code-review session**. Migration/grant state remains UNKNOWN
without authorized owner readback. Current production secret-name inventory
still exposes no cleanup-specific slots; generic migration/runtime/Spaces slots
are not substitutes, and secret values were never accessed.

## DATA #680 operational checklist

The owner or appropriately authorized operator must supply each approval and
receipt below. Agents can prepare/validate code and non-mutating evidence, then
execute a specifically authorized operation; they cannot supply owner decisions,
approve deployments, grant themselves access or infer approval from green CI.

| Gate | Technical preparation / verification | Owner approval or operator evidence still required |
| --- | --- | --- |
| 1. Retention policy and deadline enforcement | Owner decision is [recorded on DATA #680](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/680#issuecomment-6305035560): standard Snowflake Time Travel and Fail-safe within documented limits are permitted; active Snowflake and Spaces raw copies must be gone by capture + 30 days, using daily cleanup with deadline safeguards | Policy decision is complete. Technical enforcement remains blocked: current planner selects only at/after expiry, so a daily pass can be almost 24 hours late even without failure. Before acquisition, implement and review proactive cleanup at the existing lease/claim/procedure seam, with a safety window covering cadence, approval/execution latency and retries, monitored failure escalation, and boundary/failure tests proving deletion by the deadline. Any required SQL adjustment must be a reviewed forward migration; never rewrite V150. Do not treat reader expiry, a daily schedule or an alert alone as deletion proof. Owner must designate the responsible operator and approve production scheduling/execution separately. |
| 2. Code integration | #714 is merged at the approved head; #667 has been refreshed against resulting main without changing production safety controls | #667 still requires explicit owner merge approval of its new exact green head; do not merge it under the #714 approval. After its approved merge, verify exact merged-main checks. Promote only the existing DEV-tested immutable digest through the accepted protected path; no rebuild-for-PROD substitute or new scheduler. |
| 3. Dedicated cleanup identity/secrets | Reuse existing security/bootstrap and owner-handoff SQL templates; inventory secret names only | Authorized security owner provisions/verifies `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP_SVC` / `OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP`, a dedicated service keypair and approved execution context. Purge-owner `OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER` stays unassigned. No direct executor DELETE or API/runtime grant expansion. Record security review and effective grants. |
| 4. Spaces credential/storage boundary | Fixed bucket `one-health-lyme-gap-atlas-data-prod`, `sfo3`, HTTPS endpoint, exact `prod/prod/cdc-eid-expedited/<run>/<sha>.bin` scope; version-list/HEAD checks already implemented | Separate PROD bucket-limited cleanup key, capable of exact-key listing/HEAD/delete. Owner verifies bucket versioning is disabled and target has no retained versions/delete markers. Code prefix enforcement is narrower than bucket-level key scope; provider-enforced prefix isolation needs a recorded owner decision. Do not substitute a shared or full-access key, or broaden access for bucket configuration. |
| 5. Migration authority | Reuse V146 and V150; no new DDL or migration rewrite | Authorized migration owner reads exact full ledger and pending set. Verify V146 filename/SHA `85a2fd022e4024bfb0217bad6cec78bdfcd1da255a662ebd5c48c7a073eb22dc`. If absent, use its separately approved protected deployment first. V150 SHA `883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb` must be the sole pending version in its protected lane. Do not absorb unrelated pending migrations into this approval. |
| 6. Procedure handoff | Existing verifier checks attestation, exact creation time, owner and narrow procedure grants | After V150, authorized SECURITYADMIN performs reviewed ownership transfer with `REVOKE CURRENT GRANTS`, verifies dependencies, grants executor USAGE last and inserts one immutable reviewed attestation. Verify dedicated actor identity and no unexpected outbound grants. Missing visibility is UNKNOWN, never absence or authority. |
| 7. Synthetic pair creation | Fixed run `synthetic-proof-680`, artifact SHA `35347e7199b7892e7a0202ed72eafc0147f5a28d1042f27a59d595c9d45fa6b2`; immutable expired lease and two claims using the existing ledger | Separate creation authorization covers exact nonpublisher synthetic bytes, source/version/hash, capture/expiry, checkpoint and object. Creator supplies and verifies actual byte hashes in both stores, with real `xml_base64` and artifact fields in the checkpoint. A claim or metadata marker alone is insufficient. No pair was created here. |
| 8. Read-only dry run | Existing `dry-run` is SELECT/list/HEAD only, uses named audit PAT plus dedicated inspection key and a private exclusive plan file; double snapshot detects observed drift | Successful receipt must show one target/two copies, both stores present, no extra eligible targets, and provider writes/deletes false. Human audit deliberately reports executor proof false; use the separate intended-actor/handoff verification. Restrict the plan directory ACL on Windows and never publish locators or keys. |
| 9. Exact-plan approval / deletion proof | Existing separate approver, durable guard, per-copy pending/outcome audit, version rejection, confirmed absence and same-plan idempotent retry | Separate independent plan approval reference and explicit deletion authorization bound to the exact frozen plan SHA. Under dedicated executor only, delete the one synthetic pair. Read back checkpoint 1 -> 0, object HEAD -> 404, no retained versions, stable normalized item/revision/capture/acquisition-context/source/provenance counts and hashes. Retry same file/hash -> already absent. Test wrong-scope denials offline; do not attempt unauthorized PROD deletes. Record exact code SHA/digest, roles, grants, plan, receipts and retention limitation. |
| 10. EID registration | Existing fixed `register-prod-eid.yml` and immutable reviewed source document; V146 exact receipt plus empty eligible pending set | Only after #680 acceptance, separate owner approval and native protected production approval for this single registry write. Re-read exact source v1/hash/state/rights and intended-role V2 access. Registration itself does not acquire bytes. |
| 11. One bounded EID acquisition | Existing `run-prod-ingestion.yml` exact EID route and canonical orchestrator; 2 MiB / 250 items / 30-second fetch / no redirects / one attempt; fixed policy and runtime identity | Separate owner and native production approvals for one `operation=run` on exact green merged main; no fixture/dry-run/resume/alternate feed. Verify actual acquisition/checkpoint/object/normalized provenance, unchanged duplicate repoll semantics where separately authorized, and a genuine EID row in `PRESENTATION.INTELLIGENCE_FEED_V2`. Quiet/empty success is not a real-row acceptance. |

Provision dedicated credentials under separate approved secret slots or an
owner-controlled operator context. Existing runner settings use `SNOWFLAKE_*`
and `SPACES_*`: map only the dedicated actor/key into those process-local names;
never overwrite shared production environment slots. The read-only inspection
key uses `INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID` and
`INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY`. Never put values in arguments,
tracked files, workflow output or this checklist.

## Runnable prepared sequence (not execution authorization)

After **both PRs have approved merges**, pin the reviewed current-main SHA and
already DEV-tested image digest. All commands below that write or dispatch a
production workflow require the corresponding explicit approval above; none
was run in this session. Do not fill missing approval references with placeholders
and execute. Owner readbacks resolve actual current ledger state first.

```powershell
$repo = 'Caraway-Labs/one-health-lyme-gap-atlas-data'
$reviewedMain = '<exact-approved-green-main-sha>'
$devTestedDigest = 'sha256:<already-dev-tested-digest>'
$pendingV150 = '[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql","sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"}]'
# Gate 5 only: V146 already applied, V150 alone pending, native approval still required.
gh workflow run promote-prod.yml -R $repo --ref main -f "reviewed_commit=$reviewedMain" -f "image_digest=$devTestedDigest" -f "expected_pending_json=$pendingV150" -f protected_intelligence_prerequisite=true
# Gate 6: security owner separately performs the reviewed handoff, then dedicated actor preflight.
uv run python -c "from scripts.intelligence_raw_cleanup_prod import factory,identity,EXECUTOR_USER,EXECUTOR_ROLE; from lyme_gap_atlas_data.intelligence_raw_cleanup import verify_prod_cleanup_handoff; identity(factory,EXECUTOR_USER,EXECUTOR_ROLE); verify_prod_cleanup_handoff(factory)"

# Gate 7: separately authorized creator installs and verifies only the named pair.
# Gate 8: restricted directory already provisioned; dedicated inspection key supplied process-locally.
$privatePlan = '<restricted-directory>/synthetic-680-plan.json'
uv run python scripts/intelligence_raw_cleanup_prod.py dry-run --plan-file $privatePlan

# Gate 9 only, after exact-plan review and explicit deletion authorization.
$planSha = '<exact-frozen-private-plan-sha256>'
$approvalRef = '<recorded-approved-review-reference>'
# Separate migration/approval actor:
uv run python scripts/intelligence_raw_cleanup_prod.py approve --plan-file $privatePlan --plan-sha256 $planSha --approval-ref $approvalRef --confirm
# Dedicated cleanup actor/key; never a shared ingestion credential:
uv run python scripts/intelligence_raw_cleanup_prod.py execute --plan-file $privatePlan --plan-sha256 $planSha --confirm
# Independently verify before/after state, then authorized same-plan idempotency retry:
uv run python scripts/intelligence_raw_cleanup_prod.py execute --plan-file $privatePlan --plan-sha256 $planSha --confirm

# Gate 10 only, after #680 acceptance and separate registry-write approval:
gh workflow run register-prod-eid.yml -R $repo --ref main -f "reviewed_commit=$reviewedMain" -f 'expected_pending_json=[]' -f accounting_confirmed=true
# Gate 11 only, after separate acquisition approval (UUID fields deliberately omitted for fixed EID):
gh workflow run run-prod-ingestion.yml -R $repo --ref main -f source_definition=config/sources/intelligence_cdc_eid_expedited.yml -f operation=run -f "release_commit=$reviewedMain"
```

Once a real V2 row exists, verify the **actual API service identity**, not only a
human READ role or CI, and a genuine bounded API article response. API #172
enablement and WEB #429 remain separately approved follow-on work. Preserve the
existing release-completeness controls if any semantic release is changed; this
feed reconciliation neither changes its pointer nor bypasses its gates.

**Single immediate owner action:** review the refreshed exact green head of PR
#667 and explicitly approve its merge. It remains unmerged. For subsequent
production activation, the next separately authorized operator action is the
dedicated cleanup identity/key bootstrap in gates 3-4, with migration/security
readbacks determining gates 5-6. Deadline enforcement in gate 1 is an unresolved
technical prerequisite before any feed acquisition. Synthetic creation, physical
deletion proof, source registration, acquisition and API enablement each retain
their separate approval gates; merge approval cannot substitute for them.
