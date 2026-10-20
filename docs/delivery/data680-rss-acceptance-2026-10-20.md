# DATA #680, #132 and #135: bounded EID delivery audit

As of October 20, 2026, America/Denver. Audited main:
`ce77e47d3ba5d95d465c482d4ac87166202d3dae`.
Worktree: `C:/codex_programming/worktrees/data680-rss-acceptance-20261020`;
branch: `codex/data680-rss-acceptance-20261020`.

Outcome: retain the existing RSS adapter, canonical state machine, Snowflake
storage, V146/V150 migrations, exact-plan approval and owner-handoff controls.
Add only read-only synthetic-pair inspection and verified Spaces deletion.
PROD acquisition, registration, synthetic creation, deletion, deployment,
approval insertion, API activation and merges were not performed.

## Current evidence

| Check | Current result | What it proves |
| --- | --- | --- |
| PAT `ATLAS_PROD_READ`, explicit `COMPUTE_WH` | `MATTHEWCARAWAY / OH_LYME_PROD_READ / ONE_HEALTH_LYME_GAP_ATLAS_PROD / COMPUTE_WH` | Human read-role context only |
| `SELECT COUNT(*) FROM PRESENTATION.INTELLIGENCE_FEED_V2` | `0` | V2 exists and human READ can query it; no published row; not API-service access |
| PAT `ATLAS_PROD_RUNTIME_AUDIT` | `MATTHEWCARAWAY / OH_LYME_PROD_RUNTIME / ONE_HEALTH_LYME_GAP_ATLAS_PROD / OH_LYME_PROD_INGEST_XS_WH` | Human runtime-audit context only |
| Registry versions, bounded query under runtime audit | `[]` | No PROD intelligence source rows at inspection time |
| Raw-retention documents grouped by type under runtime audit | `[]` | No PROD lease/copy documents, including the named synthetic pair |
| V146/V150 ledger query under runtime audit | Object not found or not authorized | Exact migration status UNKNOWN; do not infer absence or use an admin fallback |
| `SHOW TABLES` for checkpoint table | Permanent `TABLE`, `retention_time=1`, owner `OH_LYME_PROD_MIGRATION_DEPLOYER`, 4 rows | Shared checkpoint storage exists; these rows are not identified as EID and must not be deleted |
| New read-only dry run against PROD | `INTELLIGENCE_RAW_EXACT_SYNTHETIC_PAIR_REQUIRED`, exit 1; no plan file | Empty ledger rejected before Spaces access; not a passing deletion proof |
| Dedicated cleanup credentials | No cleanup-specific secret names in GitHub `production`; no cleanup/Spaces/AWS process variable names | Credentials unavailable in inspected execution surfaces; not proof identities do not exist elsewhere |
| Spaces live `HEAD` / version inventory | NOT RUN | No authorized dedicated key and no claimed synthetic target; provider state remains UNKNOWN |
| DEV READ source-registry read | Not authorized / not visible | Current private DEV registry state UNKNOWN under this role; historical EID success is not refreshed live evidence |

The historical DEV slice recorded in issue comments has two real EID items and
an idempotent repeat. It does not prove PROD readiness. The observed V2 view and
retention table supersede the older assertion that those objects are absent;
they do not prove the exact V146 checksum is applied. No higher-privilege role
was used to resolve visibility gaps.

## Review against acceptance

| Issue | Main implementation | Unmet acceptance |
| --- | --- | --- |
| [#680](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/680) | V150 + fixed EID executor, independent approval, guard, immutable leases, audit, handoff templates | Dedicated actor/grants, exact ledger/handoff, live two-store synthetic dry run and separately approved deletion/retry, retention/cadence acceptance |
| [#132](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/132) | Bounded RSS/Atom transport, native mapping, private context, parser/security/quiet-poll tests, existing ingestion composition | Three of the five named approved feeds through DEV, five-feed endpoint/fixture/mapping disposition, current intended-role evidence; one EID pilot cannot close this issue |
| [#135](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/135) | V135 revisions/captures, deterministic dedup, atomic writer, V2 projection, provenance and raw expiry gates | Current intended-role readback, full approved-pilot evidence and production cleanup/activation gates; metadata-only EID is a separate bounded delivery slice |

[PR #681](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/681)
is merged at `93085a246b7962a9bad1a3f095fb5630bdc1f08d`; its reviews list is
still empty. Obtain post-merge independent review and resolve findings forward.
[PR #667](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/667)
remains OPEN at `c353eccc77f933f11f9b594e56a712664eefd6e3`, with historical exact-head
Quality success and no approval decision. It contains the existing bounded PROD
EID registration/runtime route missing from main. Reconcile it against current
main, review and rerun checks; do not reproduce that implementation here.
[PR #668](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/668)
remains OPEN at `33beac0a9ec2bb45c9456bae94e2ca12af336322`; health attribution is
independent and does not authorize or unblock raw deletion. Its broader health
correctness review need not become another ingestion framework prerequisite.

## Approved source identities

Selection is not a live immutable registry admission or a permission to publish.
The latest named five-feed pilot is `config/intelligence/feed-pilot-2026-10-06.json`.
Earlier `feed-selection-v1.json` dispositions differ and are historical.

| Identity | Exact selected endpoint | Current-main activation evidence |
| --- | --- | --- |
| `cdc-newsroom` | `https://tools.cdc.gov/api/v2/resources/media/132608.rss` | Selected; native capture fixture exists; no SourceDefinition or executable policy receipt in this slice |
| `nih-news-releases` | `https://www.nih.gov/news-releases/feed.xml` | SourceDefinition exists; historical normal-access HTTP 403; no executable policy receipt |
| `niaid-news` | Unresolved (`null`) | Selected in newer pilot despite earlier deferred disposition; exact endpoint/mapping blocked |
| `cdc-vital-signs` | `https://tools.cdc.gov/api/v2/resources/media/275866.rss` | SourceDefinition exists; selected in newer pilot despite earlier deferred disposition; no executable policy receipt |
| `who-newsroom` | `https://www.who.int/rss-feeds/news-english.xml` | Selected; no SourceDefinition or executable policy receipt in this slice |
| `cdc-eid-expedited` | `https://wwwnc.cdc.gov/eid/rss/expedited.xml` | Separate `DATA-132-135-EID-ADMISSION-2026-10-09`; sole executable receipt; not an alias for CDC Newsroom or Vital Signs |

The EID package is registry version 1, canonical source SHA256
`51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4`.
It permits title, original link, language and publisher dates with CDC attribution
and nonendorsement. Descriptions, article text, excerpts, image values/bytes,
logos and derived claims remain withheld. Raw policy is `intelligence-raw-30d-v1`;
rights receipt is `cdc-eid-expedited-metadata-raw-30d-v1`.
Do not relabel the EID source, migrate its evidence into a newsroom identity,
or change #132's acceptance without an owner decision. Endpoint availability
above is historical/selected configuration, not a new network revalidation.

## Exact blockers, in execution order

1. **Retention owner:** accept the physical-retention boundary and staffed
   deletion cadence. PROD's shared permanent checkpoint table has one-day Time
   Travel, followed by Snowflake's seven-day Fail-safe. V150 removes active rows
   but cannot prove all recoverable bytes disappear by capture + 30 days.
   If that strict interpretation is required, approve a forward adjustment at
   the existing raw-artifact/reference seam before acquisition. Do not shorten
   unrelated checkpoint retention or rewrite V070/V146/V150.
2. **Independent/security reviewer:** review merged #681 and this forward delta;
   reconcile/review #667 on current main. Historical green checks and a requested
   review do not satisfy approval. No merge is authorized by this audit.
3. **Migration owner:** read back exact V146 and V150 ledger/checksums, procedure
   body/creation time and complete pending set. Current audit role cannot see
   that ledger. If V146 is absent, apply its already-reviewed protected path
   separately. V150 must be the sole pending migration in its protected lane;
   unrelated pending migrations require their existing owners, not a bypass.
4. **Security/storage owners:** provision or identify the dedicated cleanup
   service/role and separate bucket-limited Spaces key; read back grants and
   record the external security review. Keep purge-owner unassigned and no
   executor direct DELETE. Bucket-level key capability is broader than the
   EID prefix, which the runner enforces; obtain a decision if provider-level
   prefix restriction is mandatory. Keep versioning disabled and verify no old
   versions/delete markers; do not widen credentials for configuration access.
5. **Security owner:** complete and attest the existing SECURITYADMIN handoff
   only after V150 verification. Missing intended-actor proof is still a blocker,
   even though human audit SELECT succeeds.
6. **Fixture owner:** separately authorize creation of the exact synthetic
   expired lease, claimed checkpoint and claimed Spaces object. None exists in
   the PROD ledger now. Use nonpublisher synthetic bytes, matching checksum and
   the existing contract; no direct unreviewed SQL or generic uploader is supplied.
7. **Deletion reviewer/operator:** obtain successful two-store dry-run receipt,
   approve its exact canonical plan/hash separately, then explicitly authorize
   one-target deletion and retry. Record before/after normalized lineage and
   raw presence. An inspection receipt is not deletion authorization.
8. **Release/source owner:** only after #680 acceptance, separately authorize
   exact EID registration and one bounded acquisition through reviewed #667.
   Verify actual API service-role access and one real article before API #172
   activation and WEB #429. No zero-row response counts as a live article.

Provider details: [Spaces versioning](https://docs.digitalocean.com/products/spaces/how-to/enable-versioning/),
[limited-key restrictions](https://docs.digitalocean.com/products/spaces/details/limits/),
[Snowflake Time Travel](https://docs.snowflake.com/en/user-guide/data-time-travel)
and [Fail-safe](https://docs.snowflake.com/en/user-guide/data-failsafe).

## Runnable acceptance sequence

Run from this isolated worktree. The following read-only checks are authorized;
stop on any failed identity check. No secret values are arguments.

```powershell
uv sync --extra dev --extra pipeline --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run dbt parse --project-dir dbt --profiles-dir dbt
docker build --tag atlas-data680-review:local .
docker run --rm atlas-data680-review:local /app/.venv/bin/atlas-data pipeline --help
docker run --rm atlas-data680-review:local /app/.venv/bin/dbt parse --project-dir /app/dbt --profiles-dir /app/dbt --no-partial-parse
snow sql -c ATLAS_PROD_READ --warehouse COMPUTE_WH -q 'SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()' --format JSON
snow sql -c ATLAS_PROD_READ --warehouse COMPUTE_WH -q 'SELECT COUNT(*) AS N FROM PRESENTATION.INTELLIGENCE_FEED_V2' --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q 'SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()' --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q 'SELECT source_id,registry_version,registry_sha256 FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS ORDER BY source_id LIMIT 10' --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q 'SELECT document_type,COUNT(*) AS N FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS GROUP BY document_type' --format JSON
```

After separately approved synthetic creation and dedicated Spaces key provisioning,
use a restricted private directory outside Git. This command itself never writes
to either provider; missing prerequisites intentionally fail:

```powershell
$privatePlan = Join-Path $env:LOCALAPPDATA 'AtlasPrivate/data680/synthetic-plan.json'
# Owner first establishes the private directory ACL and process-local dedicated key.
uv run python scripts/intelligence_raw_cleanup_prod.py dry-run --plan-file $privatePlan
```

Require exactly `synthetic_targets=1`, `copy_count=2`, both presence flags true,
`writes=false`, `deletes=false`. Save its hash privately. Repeating inspection at
another time produces a new planned-at/hash; retain the reviewed file unchanged.
The inspection mode requires the local Snow CLI; it is not a container job or
new scheduler. Owner-provisioned cleanup execution uses the existing runner.

The following commands are **not authorized to execute by this document**.
They are runnable templates only after the named separate approvals, in the
existing protected execution context with owner-injected credentials:

```powershell
$repo = 'Caraway-Labs/one-health-lyme-gap-atlas-data'
$reviewedMain = '<exact-reviewed-green-main-sha>'
$devTestedDigest = 'sha256:<exact-dev-tested-digest>'
$pendingV150 = '[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql","sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"}]'
# Only if owner ledger confirms V146 applied and V150 alone pending; native approval required.
gh workflow run promote-prod.yml -R $repo --ref main -f "reviewed_commit=$reviewedMain" -f "image_digest=$devTestedDigest" -f "expected_pending_json=$pendingV150" -f protected_intelligence_prerequisite=true
# SECURITYADMIN separately performs the reviewed handoff, then intended-actor proof.

$planSha = '<exact-private-plan-sha256>'
$approvalRef = '<independently-approved-review-reference>'
# Separate migration/approval identity; this INSERT requires its own approval.
uv run python scripts/intelligence_raw_cleanup_prod.py approve --plan-file $privatePlan --plan-sha256 $planSha --approval-ref $approvalRef --confirm
# Dedicated cleanup service identity + separate Spaces delete key; only after deletion approval.
uv run python scripts/intelligence_raw_cleanup_prod.py execute --plan-file $privatePlan --plan-sha256 $planSha --confirm
# After authorized readback, repeat the SAME exact file/hash: expect already_absent twice.
uv run python scripts/intelligence_raw_cleanup_prod.py execute --plan-file $privatePlan --plan-sha256 $planSha --confirm

# Only AFTER #680 acceptance, #667 reviewed/merged, and separate registration approval:
gh workflow run register-prod-eid.yml -R $repo --ref main -f "reviewed_commit=$reviewedMain" -f 'expected_pending_json=[]' -f accounting_confirmed=true
# Separate one-run acquisition approval; no source-version/decision UUID for this fixed route:
gh workflow run run-prod-ingestion.yml -R $repo --ref main -f source_definition=config/sources/intelligence_cdc_eid_expedited.yml -f operation=run -f "release_commit=$reviewedMain"
```

For synthetic deletion, before/after readback must show the exact checkpoint
count 1 -> 0 and Spaces `HEAD` present -> 404, with no retained object versions.
403 is failure. Save per-copy pending/outcome audit, approval/handoff hashes and
exact identity; retry must append already-absent outcomes without a scope change.
Use a separately authorized read-only audit session for counts, not direct table
grants to the executor. Verify unchanged source registry, item revisions, item
captures, acquisition contexts and provenance, and reject wrong source, bucket,
prefix, database, role, live lease and stale plan before mutation. Offline tests
exercise these denial paths without attempting unauthorized PROD deletes.

## Production activation checklist

- [ ] Independent review and exact-head CI for the forward delta and reconciled #667.
- [ ] Recorded retention decision covers Snowflake recovery storage; staffed physical cleanup cadence approved.
- [ ] Exact V146/V150 checksums, pending set, procedure owner/body/time and handoff verified by authorized owners.
- [ ] Dedicated cleanup user/role/key and separate bucket-limited Spaces key verified; no shared credential substitution, direct executor DELETE or assigned purge-owner role.
- [ ] Versioning disabled, version inventory supported by limited key, no retained versions/delete markers; owner configuration readback recorded.
- [ ] Separate synthetic creation approval; exact paired target exists and nonpublisher contents are hash bound.
- [ ] Successful live SELECT/list/HEAD dry run, exact private plan, independent plan approval and explicit deletion approval recorded separately.
- [ ] One-target deletion + retry + negative scope evidence; normalized metadata/provenance unchanged.
- [ ] Exact reviewed DEV-tested artifact and existing protected promotion accepted; no topology replacement or new schedule.
- [ ] Separate EID registration approval; source v1/hash/rights re-read in PROD.
- [ ] Separate one-run acquisition approval; endpoint revalidated via existing bounded adapter, metadata-only output and immutable raw lease checked.
- [ ] Real API service identity reads V2; one genuine EID article returns title/original URL/publisher/date states/source/retrieval/method/limitations, with forbidden fields absent.
- [ ] Separate API activation authorization; only then WEB #429. Disable feed/flag for rollback; keep append-only evidence and never widen scope.

## Validation record

Focused raw-retention/cleanup checks passed: **50 passed**, including exact
30-day expiry, missing pair, additional target, access-denial, version-history,
preflight-before-checkpoint-mutation, post-delete absence, CLI redaction and
missing-key cases. Ruff lint/format, mypy (149 source files), dbt parse and the
initial container build passed. Final full-suite/container smoke results are
recorded in the PR and task completion report. The live dry run failed closed as documented above;
there is no successful live Spaces, deletion, intended-cleanup-actor or ingestion
evidence in this change. No issue is eligible for closure based on this audit.
