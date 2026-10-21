# PROD EID proactive raw cleanup: 30-day maximum

Owner policy: [DATA #680 decision](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/680#issuecomment-6305035560).
Raw operational copies must be absent from active Snowflake and Spaces storage
by initial successful capture + 30 days. Standard Snowflake Time Travel and
Fail-safe recovery within documented platform limits is permitted. Eligible
normalized metadata and immutable provenance remain long-lived.

## Existing-seam correction

The immutable lease remains capture + 30 days. For PROD `cdc-eid-expedited`
only, exact-plan cleanup becomes eligible at **deadline minus 48 hours** (day
28), including equality at microsecond precision. DEV and other feeds retain
their existing expiry-only behavior. Thirty days is a maximum, not a minimum:
raw read/write/resume and conditional reuse stop at day 28 before loading bytes;
this also prevents a checkpoint resave from recreating an already-cleaned copy; no lease renewal,
304 extension or fresh claim may recreate expired bytes.

Every claim must reach its applicable boundary and every selected claim must
fit the exact source/scope. A newer shared claim continues to block deletion.
Physical keys in the EID path are per-run; any unexpected shared claim is an
acceptance failure to investigate, not permission to retain an older copy past
its deadline. Do not admit a shared-key arrangement that defeats the maximum.

V162 is an append-only PROD forward migration, preserving V150 bytes. It replaces
only the existing checkpoint purge procedure and its expected-handoff view.
It retains identity, exact-plan approval, committed intent, guard, immutable
30-day lease and payload-match checks; only eligibility is advanced. Replacement
drops executor USAGE and requires fresh owner/body/creation-time attestation.
Old attestations remain immutable; verification selects the new migration hash.
No procedure usage or ownership handoff is granted by the migration.

## Daily execution and failure acceptance

No scheduler, deployment or approval is enabled by this PR. Before acquisition,
the operator must configure and demonstrate these conditions using the existing
approved execution context, with a designated owner and recorded escalation:

1. Cleanup runs at least once every 24 hours. Copies enter eligibility at day 28;
   even the worst daily phase leaves at least 24 hours until the hard deadline.
2. The separate approver reviews each exact private plan. Plan approval and
   execution must complete within 12 hours of that daily run. Never auto-approve
   plans, widen scope, use shared keys, or bypass the durable guard to meet time.
3. A provider/audit/commit failure is a failure, never successful cleanup. Preserve
   pending/failed evidence and independently verify stores. Retry the same exact
   approved plan idempotently if inventory is unchanged; otherwise regenerate
   and obtain fresh approval. Escalate immediately and retry within six hours.
4. Run the read-only physical-copy monitor after cleanup and at least daily. Any
   nonzero exit, timeout or missing run is an operator page. Exit 2 begins at day
   28, leaving recovery time; `urgent_copies` marks <=24 hours remaining and
   `overdue_copies` marks an actual policy breach. It checks exact-key HEAD and
   version history plus checkpoint row counts; receipts alone never prove absence.
5. Demonstrate a worst-phase daily pass, failed first execution, successful
   retry before capture + 30 days, alert delivery and missed-run detection under
   the intended credentials. The protected production synthetic test needs its
   own creation/deletion approvals. Offline/CI tests are not that evidence.

The 48-hour window removes the deterministic extra-day defect. No finite buffer
can guarantee deletion during an unbounded provider outage or absent operator
approval. Such failures require incident escalation and suspension of further
acquisition, never a claim of deadline compliance. Until the above operational
bounds and physical proof are demonstrated, DATA #680 acceptance remains open.

## Prepared commands (not execution authorization)

Use the same dedicated cleanup identity/key mapping and private plan directory
as [the existing runbook](intelligence-raw-cleanup-prod.md). The audit monitor
uses named PAT `ATLAS_PROD_RUNTIME_AUDIT` and separate dedicated inspection-key
variables. It neither creates a plan nor writes the ledger.

```powershell
# Non-mutating: no raw retrieval, SELECT/list/HEAD only. No plan file needed.
uv run python scripts/intelligence_raw_cleanup_prod.py deadline-check
# Following actions each retain the existing separate production approvals:
uv run python scripts/intelligence_raw_cleanup_prod.py plan --plan-file $privatePlan
uv run python scripts/intelligence_raw_cleanup_prod.py approve --plan-file $privatePlan --plan-sha256 $planSha --approval-ref $approvalRef --confirm
uv run python scripts/intelligence_raw_cleanup_prod.py execute --plan-file $privatePlan --plan-sha256 $planSha --confirm
uv run python scripts/intelligence_raw_cleanup_prod.py deadline-check
```

For a fresh install, V146 must already be verified/applied through its separately
approved lane. The existing protected intelligence prerequisite lane admits only
exact pinned V150 alone, V162 alone (V150 already installed), or ordered
[V150,V162] with no unrelated pending migrations. Initial [V150,V162] deployment
needs no intermediate V150 handoff. For an already handed-off V150 procedure,
the security owner must first authorize the narrowly scoped owner-preparation
template; a normal migrator cannot replace a procedure owned by the unassigned
purge owner. Then protected migration and the V162-specific final handoff each
require separate authorization. Never rerun or edit an applied migration.

The authorized human migration-role audit found V146 recorded at its reviewed
hash and, against this correction tree, only V150/V162 pending. Revalidate with
the actual protected migration service before dispatch; human PAT access is
not service-credential proof. This prepares, but does not authorize, the chain:

```powershell
$repo = 'Caraway-Labs/one-health-lyme-gap-atlas-data'
$reviewedMain = '<exact-approved-green-merged-main>'
$devTestedDigest = 'sha256:<already-DEV-tested-immutable-digest>'
$pending = uv run python -c "import json; from lyme_gap_atlas_data.migrations import PROD_INTELLIGENCE_CLEANUP_MIGRATION as a, PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION as b; print(json.dumps([a,b],separators=(',',':')))"
# STOP unless approved service preflight independently confirms this exact chain.
# Requires separate migration authorization and native production approval:
gh workflow run promote-prod.yml -R $repo --ref main -f "reviewed_commit=$reviewedMain" -f "image_digest=$devTestedDigest" -f "expected_pending_json=$pending" -f protected_intelligence_prerequisite=true
```

See [current non-mutating audit and exact credential instructions](../delivery/data680-operational-readiness-2026-10-20.md).
After cleanup acceptance, source registration, one bounded EID acquisition,
real `PRESENTATION.INTELLIGENCE_FEED_V2` rows, and API #172 activation each
retain separate approval. Web genuine-article acceptance follows the API's
actual service-identity canary; a human READ role or fixture is insufficient.
