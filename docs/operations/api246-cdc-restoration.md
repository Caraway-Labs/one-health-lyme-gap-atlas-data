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
view compilation still requires its existing deployment owner at the protected
step, rather than combining privileges or changing grants.

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
   commit and full pending checksum set (V156, and V150 if still pending).
   The script applies only V156 and verifies grant parity; V150 stays pending.
4. Through the required steward channel, inspect the private reconciled packet
   and real signed reference. The real active global steward calls
   `GOVERNANCE.SP_REGISTER_CDC_TARGET_ADMISSION` once per measure. This operation
   appends a decision and validates all 3,109 bindings; never run as pipeline user.
   Approval date stays October 17; registration timestamp is actual execution.
5. Read both measures through the actual production consumer identity and
   immutable Data producer. Confirm known NO_RECORDS remains unknown.
6. Merge/deploy the compatible API binding through its established workflow.
   API merge triggers deployment; obtain the explicit required merge approval.

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

No admission registration, merge or deployment has occurred. Local packaging and
fixtures do not prove production serving. Snowflake DDL/procedure execution and
actual registration access require protected verification. Local Docker Linux
engine is unavailable; hosted container and secret scanning remain mandatory.
