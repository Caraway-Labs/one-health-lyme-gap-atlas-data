# DATA372 delivery evidence: 2026-10-02

Draft PR: https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/564
Implementation workload head: `2515a20099b60fab2ad6cb8ea8a4be4b6f83f83a`.
Refreshed review base/main: `69b38ff26cbf40a7900852ffba0ed14de0e0c642`.
Initial implementation/DEV capture base: `c5a23105719ac77f8abbca9b613b661654e22845`.
Branch: `feat/data372-sanitized-snapshots`.
No schema/data migrations, checksum edits, credentials/grants, Web edits or deployment changes.

## Stable consumer contracts

`docs/contracts/snowflake-snapshots/v1.schema.json`,
`config/metadata-scope-v1.json`,
`docs/operations/snowflake-snapshots.md`, and
`scripts/verify_metadata_snapshot_dev.py`.
Synthetic safe examples: `docs/contracts/snowflake-snapshots/examples/`.
Reviewed actual DEV artifacts: `docs/generated/snowflake/dev-2026-10-02.snapshot.json`,
`dev-2026-10-02.report.json`, and `dev-2026-10-02.verification.json` in the same directory.
Snapshot/exporter/report versions are 1. #374/#376/#377 receive environment,
capture time, inspected alias, exact workload commit, contract/scope/evidence
hashes, partial visibility, unavailable categories and explicit omissions.
#370/#371 are closed and their actual contracts remain present. #371 covers
four operation capabilities and role aliases, not comprehensive desired schema.

## Acceptance mapping

| #372 criterion | Evidence at implementation head | Status |
| --- | --- | --- |
| Deterministic normalized content/hash | Reordered/duplicate fixtures, timestamp/head independence, separate scope/contract hashes; visibility failures change evidence hash | Verified offline |
| Stale, hidden, inherited, renamed, procedure mode, schema drift fixtures | 21 focused regression tests | Verified offline |
| Partial visibility; empty metadata never absent | Strict live `partial`, unknown object/column/capability findings, observed alias-edge positives; missing category only complete ledger SELECT rows | Verified offline and DEV |
| No public secrets, payloads, internal details | Allowlisted identifiers/enums, strict schema and hostile input tests, server-side safe DESCRIBE projection, private staging ignored by Git/Docker, full history scan | Verified offline |
| Human/machine drift without remediation | JSON report and text renderer; missing/mismatched/unexpected/stale/unknown categories; mutation_started false; no readiness PASS | Verified offline |
| Authorized DEV comparison; PROD separate | Existing ATLAS_DEV_READ identity probe and reproducible in-memory source comparison passed, 17 bounded queries | Verified DEV; PROD unverified |
| Freshness before consequential use | Reviewed 24-hour TTL, future-time/integrity/current-contract checks; immediate live revalidation required despite TTL; stale/tampered baseline skipped | Verified offline |

## Checks

Focused pytest: 21 passed. Full pytest: 2,124 passed, 19 dependency deprecation
warnings (313.84s). Ruff lint and format: passed, 408 files. Full mypy: passed,
104 source files. Local dbt parse: passed. Agent-context, provision dry-run and
Alpha release load dry-run: passed. Exact implementation Docker build:
`sha256:c73a474e8fceabdfdbbb3c4bc9b0ded97f89b199cb3dc68593684b0bb01cd486`.
Container pipeline help, metadata help and dbt no-partial parse: passed.
Pinned Gitleaks full history: 513 commits, 9.07 MB, no leaks.

Hosted Quality passed:
https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/36974994824/job/110736778674
PR workflow head: `2515a20099b60fab2ad6cb8ea8a4be4b6f83f83a`.
Actual tested checkout from checkout-step log:
`d63e46686969448acfe49eebc5a0bff7411a19b9` (PR merge ref).
Merge parents are refreshed base and implementation head; tested merge tree
`46ec1b57cb11e661169bee7c38e616fc23a085ab` equals the implementation-head tree.
DEV deployment skipped as expected for the PR workflow.
The later main refresh incorporated DATA429 (#562): four unrelated surveillance
contract, decision-packet, source and test files. DATA372 rebased cleanly and
preserved those changes; no migrations, role/capability contracts or snapshot
scope changed. The published capture retains its actual historical workload
SHA. Final review uses fresh hosted Quality on the rebased checkout, rather than
claiming the original implementation run tested the later main changes.
After rebase: 21 focused tests passed (6.97s), mypy passed for 105 source files,
Ruff lint/format passed for 413 files, agent-context and diff checks passed.

## Live and visibility limits

DEV capture completed `2026-10-02T06:51:01.419647+00:00` at the implementation
workload head, using existing `ATLAS_DEV_READ` / `OH_LYME_DEV_READ`, primary role
with secondary roles NONE. Seventeen bounded queries matched normalized source
metadata held in memory: 1 object, 2 columns, 22 grants, 1 role edge, 111 migration
versions, 0 future-grant rows and 0 procedures; unavailable categories were empty.
Empty unavailable categories mean queries completed, not complete visibility.
The execution session separately checked strict schema, source comparison and
privacy before publication; independent PR merge review remains pending.
No raw source responses were persisted or published.

`GOVERNANCE.INGESTION_RUNS`, `PRESENTATION.GOVERNED_RELEASES`, and
`PRESENTATION.V_COUNTY_ATLAS_CURRENT`, plus four reviewed columns, were not visible:
unknown, never confirmed absent. Three desired runtime capabilities remain unknown.
Empty future-grant output cannot prove no future grants exist. Visible grants
outside the curated four-operation desired contract are unexpected observations,
not proof of unauthorized grants. V033 checksum differs; approved legacy
reconciliation was not inspected, so this is unknown rather than an alleged defect.

PROD, optional procedure execution mode and procedure ownership are unverified.
Default procedures scope is empty; default
county-view scope observes presence/kind, omitting columns/definition. Columns
are reviewed key-column metadata only. PUBLIC, secondary roles, database roles,
legacy child roles, unallowlisted owners/hierarchy, unreviewed types/identifiers,
measure metadata, exact publication tuples and lineage receipts are outside scope.
Unknown ownership is a safe alias, not an inferred missing owner.
SHOW/Information Schema visibility is role filtered; absence is never inferred.
Each query is a separate primary-role named session and sampling is non-atomic.
Migration checksum differences remain unknown pending approved legacy-reconciliation
evidence; LF/CRLF equivalents match. No snapshot authorizes a mutation.

## Deployment and remaining work

No migration or bootstrap needed. The sanitized reviewed artifacts were published after
source comparison. Parent coordinates independent review, latest-main refresh,
exact final-head CI, merge and serialized existing deployment. Record the exact
immutable deployed digest and functional proof separately; no deployment has
occurred through this draft PR. Any evidence-only follow-up commit requires a
new exact-head CI result before merge. Final evidence-head CI, independent merge
review and any authorized deployment remain parent-coordinated; neither merge nor
deployment is claimed here. The existing documented `ATLAS_PROD_RUNTIME_AUDIT`
route was not used; no broader grants or hidden role assumptions were introduced.
