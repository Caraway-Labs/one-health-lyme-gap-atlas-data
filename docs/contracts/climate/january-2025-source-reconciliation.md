# Bounded January source reconciliation (DATA #443 / #496)

The user approved the January 2025 descriptive weather pilot: ingestion,
Snowflake modeling and API exposure. The exact statement and relayed provenance
are in `january-2025-product-approval.json`. That record supplies product scope,
not checksums, scientific approval, steward-review evidence, grants or production
acceptance. Further historical ingestion remains deferred.

Fresh 2026-10-03 read-only inspection authenticated the existing DEV READ and
OWNER connections to their documented roles and suffixed DEV database. OWNER
successfully selected both retained RAW_ARTIFACTS for selected run
`c2eb2146-005d-44d2-bac4-e2805ca42577`; hashes and byte counts matched the review
packet. The source-version query for that run returned zero rows. A bounded
catalog search by nClimGrid/TIGER resource names and matching retained NOAA/TIGER
URLs returned zero rows, as did the related dataset-key search. These successful
scoped observations do not establish absence of differently named registry
records or any PROD object/data state. An initial query incorrectly used
RAW_ARTIFACT_ID in DATA_SOURCE_VERSIONS; after schema inspection it was corrected
to ARTIFACT_ID. The failed query is not used as absence evidence.

The existing OWNER session is MATTHEWCARAWAY; APPROVAL_STEWARDS returned one active
GLOBAL entry for that user. SHOW GRANTS confirmed OWNER's existing INSERT/SELECT
on MANUAL_REVIEW_DECISIONS and DATA_SOURCE_VERSIONS. OWNER has read access, rather
than registration INSERT, on CATALOG_DATASETS/CATALOG_RESOURCES. The existing DEV
runtime registration boundary has INSERT/SELECT on those tables. No role was
changed, broadened or granted, and no source/approval/publication row was written.

`climate_source_review.py` and `scripts/reconcile_january_climate_inputs.py`
provide the narrow continuation for independent review. They are not ingestion
commands, a second approval console, or a new owner-rights procedure. V075 remains
unchanged and CDC-only. No source-specific allowlist widening or substituted CDC
key is used.

The default phase is fixed read-only `inspect`. After review, `register-pending`
requires the existing OH_LYME_DEV_RUNTIME identity and exact DEV database. It
revalidates completed run and both retained hashes/byte counts, fails on ambiguous
or conflicting identities, reuses matching dataset/resource/version records, and
inserts only missing factual MANUAL catalog records plus PENDING versions with
approved_decision_id NULL. New resource records are inactive. No activation,
recapture, source approval, release or grant occurs. The proposed TIGER resource
key is explicitly `census_tiger_2025_us_county_analysis`; it is a reviewed new
registry proposal, not a claim that an artifact member name was already a
governed key. Existing differently named matching URL identities cause a conflict
for reconciliation rather than duplicate registration.

The `record-steward` phase separately requires the existing OH_LYME_DEV_OWNER,
current-user match to the actual reviewer, active GLOBAL steward authorization,
real dated decision evidence in a linked issue comment/PR review, rationale and
the four exact draft metadata revision pins from the existing review packet.
Generic product approval cannot satisfy these inputs. It appends conditional
January-only review decisions and new CONDITIONAL versions linked to their real
decision IDs, preserving the factual PENDING versions and all previous evidence.
It does not mark final metadata as REVIEWED; final metadata must bind those live
versions, real reviewed time and approved CONSUMER_SAFE visibility, then recompute
content-addressed revisions and pass existing release validators. No sample
decision file pretends that actual acceptance occurred.

Both mutating phases own one explicit transaction and roll back every write on
failure. Deterministic registration IDs make repetition observable; steward
repetition requires reconciliation and never silently updates a prior decision.
Run only with the appropriate already configured authorized runtime/owner. No
credentials are discovered, copied or configured by these scripts. No protected
mutation has been dispatched. The Python tests are fixture evidence for authority,
conflicts and rollback, not Snowflake DML compilation or live approval proof.

Before publication, independently review this code, run exact-head CI, execute
the separately reviewed registration/actual-decision actions, and retain verified
ledger readbacks. Then assemble final metadata and frozen membership, reverify
the full canonical target candidate, prove protected publication identity's
canonical-partition reads, actual API-reader identity and view-only grants, and
protected publication/rollback. Missing visibility remains UNKNOWN. Any new
persistent grant or credential action needs its precise authorization.

V136 remains DEV-only. PROD requires its own reviewed SQL, retained capture/target
parity, source authority, publication and reader evidence. This draft does not
promote DEV artifacts by asserting PROD availability. API #84 is coordinated on
its isolated draft; no Web changes are made. DATA #443 owns historical scope and
DATA #431 already owns calendar/window/aggregation/coverage/availability semantics
for any later monthly summary. No duplicate Epic or Story is created.
