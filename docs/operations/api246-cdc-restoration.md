# API #246 CDC restoration evidence and protected handoff

Owner decision: A-C conditional approval and D required, 2026-10-17, in the
current Codex conversation. Primary issue:
https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-api/issues/246

## Evidence collected before production writes

Named `ATLAS_PROD_READ` identity: MATTHEWCARAWAY / OH_LYME_PROD_READ /
ONE_HEALTH_LYME_GAP_ATLAS_PROD / COMPUTE_WH, empty secondary roles.
Current pointer and bundle equal the exact approved October 15 target.
October 6 is the retained donor, not a serving fallback.

Twelve serial narrow county-prefix queries (six per measure), bounded at 30
seconds each, replaced the timed-out broad lineage aggregate. Both releases
contain 3,144 distinct county observations per measure, with identical inspected
source/version/run/artifact/record hashes, values/states, publisher coverage,
retrieval and transformation fields. Exactly 3,109 per measure join authoritative
CDC conformed evidence; 35 unmatched placeholders remain excluded.

Offline validation checked all 6,218 donor semantic revisions against retained
admission and the unchanged mapper. Proposed target bindings preserve the same
physical and semantic identities; revision 3 preserves revision 2 meaning and
definition. Genuine donor receipt and active-steward review were read, not
invented. All private snapshots and proposed record maps remain gitignored in
`artifacts/api246/`; no private IDs or hashes belong in issue comments.

Supplemental named `ATLAS_PROD_OWNER` read-only inspection verified its actual
MATTHEWCARAWAY / OH_LYME_PROD_OWNER / PROD / OH_LYME_PROD_APPROVAL_XS_WH identity
and empty secondary roles first. All 3,144 raw observation rows per measure
match completely after excluding only release-local ID, release ID and creation
timestamp; distinct IDs/counties are 3,144 on each side. Source, dataset and
measure definitions each have exactly two matching pairs and zero differences.
This includes quality, missingness, limitations and persisted interpretation.
No grant expansion or production write was used. The ordinary reader cannot
read raw tables, while the owner cannot read the lineage schema; complete new
view evaluation therefore uses its existing deployment owner, rather than
combining privileges or changing grants. Named ATLAS_PROD_MIGRATOR identity was
verified separately (MATTHEWCARAWAY / OH_LYME_PROD_MIGRATION_DEPLOYER / PROD /
OH_LYME_PROD_APPROVAL_XS_WH, empty secondary roles). SELECT-only evaluation
caught Snowflake's wildcard-in-join and correlated-subquery restrictions. The
refined ordinary-join expression then returned both tick 01001 and pathogen
06001 with equivalent=true and exactly one genuine donor receipt, in 16.392
seconds including CLI/connection startup. This is not HTTP/application latency.
Actual DDL/procedure execution, full deployed cardinality and serving readback
remain protected acceptance requirements.

The global release schema/methodology differs (1.0.0 / semantic-1.0.0 donor,
2.0.0 / semantic-2.0.0 target); release limitations match. This is the existing
reviewed exact-pair DATA #443 exception, documented in
`docs/contracts/climate/january-2025-cdc-copy-reuse.md`, not a new scientific
definition or unapproved broad version exception. V156 requires those exact
version values and unchanged CDC persisted meanings.

## Required protected sequence

1. Resolve all code review and quality failures; obtain explicit human merges.
2. Build the exact reviewed Data main image, pass hosted checks and established
   DEV proof, then obtain protected PROD approval for that same digest.
3. Dispatch `promote-prod.yml` with `cdc_admission_only=true`, exact reviewed
   commit and the exact reviewed V150/V156 pending set below.
   The script applies only V156 and verifies grant parity; V150 must stay pending.
4. Through the existing named human-steward connection (not Streamlit), inspect the private reconciled packet
   and real signed reference. The real active global steward calls
   `GOVERNANCE.SP_REGISTER_CDC_TARGET_ADMISSION` once per measure. This operation
   appends a decision and validates all 3,109 bindings; never run as pipeline user.
   Approval date stays October 17; registration timestamp is actual execution.
   The owner's explicit one-time channel exception of October 17 is recorded in
   ADR 0044. It preserves all scientific/production controls and establishes no
   general waiver of ADR 0027. Separate protected production approval is still
   required before executing this registration.
5. Read both measures through the actual production consumer identity and
   immutable Data producer. Confirm known NO_RECORDS remains unknown.
6. Merge/deploy the compatible API binding through its established workflow.
   API merge triggers deployment; obtain the explicit required merge approval.

## Protected inputs and deployment recovery

Use the existing `promote-prod.yml` workflow. No new dispatch input, connection,
credential, infrastructure or migration is introduced by the retry correction.
All of these inputs exist in that workflow:

| Input | Reviewed value |
| --- | --- |
| `cdc_admission_only` | `true` |
| `january_climate_only` | `false` |
| `january_bulk_recovery_only` | `false` |
| `january_point_query_only` | `false` |
| `county_context_only` | `false` |
| `protected_intelligence_prerequisite` | `false` |
| `reviewed_commit` | Actual reviewed green **merged Data main SHA**, equal to the run's `GITHUB_SHA` |
| `image_digest` | Actual immutable image digest for that SHA, already active and tested in DEV |
| `expected_pending_json` | Exact reviewed JSON array below for initial application |

The final merged SHA and built/DEV-tested digest do not exist before human merge
and protected DEV execution. Do not substitute the PR head, invent a digest or
dispatch this template as-is. The workflow independently checks DEV's digest and
the `sha-${GITHUB_SHA}` image manifest before the migration step on **every** run.

Source-derived initial pending metadata (not a claim about a newly inspected
production ledger; revalidate through the authorized named identity before
dispatch):

```json
[
  {
    "version": "V150",
    "filename": "V150__prod_intelligence_raw_cleanup_authority.sql",
    "sha256": "883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"
  },
  {
    "version": "V156",
    "filename": "V156__cdc_current_release_consumer_authority.sql",
    "sha256": "c35bcbe24a88d31ef4f2325217735e474064348f484d1415ff1de78f5368df4f"
  }
]
```

If V156 applied successfully and the later image promotion fails, preserve the
original run, reviewed SHA, expected inputs and approved DEV-tested digest.
Inspect the provider's actual ACTIVE/failed deployment before claiming rollback
or success. A failed provider command alone does not establish which image is
active. Obtain the required production-environment approval for recovery and
rerun the failed `promote` job of that **original run**, retaining its source SHA
and dispatch inputs. This reruns all preceding digest, identity and migration
checks; do not resume at the provider step or switch to normal promotion.

The CDC driver accepts either the original V150+V156 review or an explicitly
refreshed V150-only review at the same reviewed source SHA. It removes V156 from
the reviewed pending comparison only after proving exactly one ledger receipt
with its source filename, exact checksum and that same deployment commit. It
validates all other applied checksums, unique/known ledger versions, required
V149/V155 prerequisites, actual pending set, exact release/bundle, existing view
grant parity and procedure ownership. Output `applied=[]` and
`validated_resume=true` means these checks passed, not that they were skipped.
V156 is not replayed; V150 is neither executed nor accepted as already applied.
No stewardship decision is registered by either initial application or retry.

The supported historical PROD V022/V028 ledger remains immutable. The only
accepted duplicate is exactly two pinned V028 rows with the historical filename
and checksum, accompanied by the exact V022 variant and valid retained PROD
reconciliation evidence for both versions. Initial application and retry validate
this shape through the existing legacy reconciliation rules; they neither repair
nor replay historical rows. Other duplicates, including V156, fail closed.

An empty review, unexpected duplicate/unknown ledger, wrong filename/checksum/commit,
unexpected pending migration, changed pointer or grant state blocks recovery.
If DEV has moved to another digest, the original run must fail its digest check;
restore the approved DEV proof through the protected process or obtain a new
recorded recovery decision. Do not change the V156 ledger or use a different
commit to bypass its receipt. Partial DDL without a successful ledger receipt is
not this validated image-failure case; stop for bounded protected inspection.

Before registration, separately validate the actual full secure view and
procedure under the deployment owner, including successful DDL, owner/reader
grants, 3,144 distinct rows/IDs/counties per measure, 3,109 donor-equivalent rows,
35 excluded rows, unchanged donor cardinality and actual consumer visibility.
The prior SELECT-only samples do **not** prove V156 is deployed or that these
complete checks passed. Record the approved digest and deployment receipt.

If a promoted image must be rolled back, use the existing protected deployment
runbook and the previously recorded approved digest. Leave applied V156 and its
ledger checksum intact; never rewrite historical receipts, decisions or the
current release pointer. Keep the API deployment held until Data admission and
consumer readback pass. After an API rollout, rollback uses its established
protected deployment workflow and a compatible previously approved artifact;
do not compensate by falling back to October 6 or weakening admission.

## Production acceptance

Record exact deployed source SHA/digest and admission decision IDs privately.
Use anonymous serial HTTP requests with at least 0.3 seconds after completion,
a maximum budget of 30 requests, no automatic retries, and stop batch escalation
on repeated 5xx or any 429 (honor Retry-After). Start each measure at county
01001, then admitted historical examples 13081 (tick), 19135 (pathogen) and
12047 (NO_RECORDS). Require HTTP 200 JSON, exact target release, cumulative
2025-12-31 dates, publisher-backed value/normalized state, provenance and limits.
Unknown/unadmitted placeholders must fail closed, never become negative.

Only after healthy singletons test 2/5/10 counties and pagination with
page_size=1. Check no duplicates/loss, stable source identities, release-bound
tokens and completion time against existing query deadlines. Test invalid annual
filters yield structured 400. Validate one existing human, climate and each of
five socioeconomic measures within the budget. Larger batches/national coverage
require separate measured evidence; do not infer them from these samples.
Capture status, content type, duration, request/correlation ID and gateway headers.
Post safe acceptance evidence to API #246 and close only after the preventive
gate, required reviews/approvals and all production conditions pass.

## Current limitations

For API #246, the owner's final review direction explicitly uses independent
source review followed by explicit human owner review. The unavailable `.agent`
coordinator was not invoked and must not be reported as completed. This recorded
task-specific direction does not change branch protections or establish a general
review-policy exception. Required GitHub checks, resolved conversations, human
merge decisions and protected production approvals remain in force.

No admission registration, merge or deployment has occurred. Local packaging and
fixtures do not prove production serving. Snowflake DDL/procedure execution and
actual registration access require protected verification. Local Docker Linux
engine is unavailable; hosted container and secret scanning remain mandatory.
