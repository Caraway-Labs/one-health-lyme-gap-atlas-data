# Executable January climate release extension

DATA #443 / #496; API #84 consumes the separately named daily views after review,
protected publication and intended-reader proof. No new platform or pointer.

`climate_release.py` validates optional `climate_extension` in the existing
release manifest. The five annual source slots and 14 observations per county
remain unchanged. Existing bundle hashing includes the complete extension.
Build verifies it before inserting the release; publish and rollback load and
revalidate the **persisted** extension before any release status/pointer mutation.

The extension has exact fields: `contract_version` =
`atlas-january-climate-release-extension-v1`; January `period`; selected
`ingestion_run_id`; verified `candidate_sha256`; `capture_membership_sha256`;
389,856 `row_count`; four complete `metadata` revision objects; `sources` with
NOAA and TIGER source-version/artifact/hash pins; and `review_evidence` with
reviewed commit, actual GitHub review URL and reviewer. No invented approvals
or placeholder source-version IDs belong in an executable release manifest.
There is deliberately no sample manifest pretending to contain live approval.

Membership digest is SHA256 over UTF-8 lines of compact JSON arrays
`[capture_record_id, record_revision, record_id, source_row_hash, normalized_sha256]`,
ordered strictly by capture_record_id, one newline per tuple. All 389,856 selected
V103 revisions must match; no extra revisions in the selected run are accepted.
Both approved source versions must join their retained artifacts and this run.
Run completion, passing quality and native January resource/measure/normalization
and NOAA/TIGER hashes are rechecked at activation. Missing or inaccessible
authority fails closed. This does not transport DEV captures into PROD.

Method `/2` requires semantic version `2.0.0` under existing semantic governance.
Historical `/1`, `1.0.0` remains unchanged; no scientific equivalence is asserted.
The four definitions describe the already verified candidate, with explicit
valid/source-supported daily completeness and separate monthly support fraction.
Actual reviewed metadata and review evidence remain publication prerequisites.
Metadata alone, even marked REVIEWED, cannot gain arbitrary consumer visibility.
The default validator still blocks derived exposure. The release extension
explicitly supplies approved revision IDs only after its exact review/source
structure is validated, and accepts only the four canonical climate meanings,
CONSUMER_SAFE visibility, January period and source-backed evidence. PUBLIC and
unrelated derived measures remain blocked. Consumer-safe metadata undergoes
the existing sensitive-field/value checks. Source authority is then rechecked
against retained ledgers before publication or rollback.

`sql/january_climate_consumer_views.sql` contains the two exact proposed views:
`PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V` and
`PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V`. It is outside the migration
runner pending exact review and owner reservation of a migration number. It
contains no GRANT and has not been executed. Existing V103 migration-deployer
SELECT is the proposed view dependency; effective ownership and intended reader
SELECT on these two views require read-only proof before deployment. No reader
needs revision/artifact table access.

Views use the existing ATLAS pointer and PUBLISHED release's selected run and
four metadata objects. A release without this extension yields no climate rows;
existing pointer rollback controls both annual and daily exposure. Native DOUBLE
values use AS_DOUBLE, with no TO_JSON reconstruction or precision-reducing casts.
Support quantities retain native VARIANT numeric storage, including DECIMAL.
The allowlist excludes internal capture/run/artifact IDs, hashes and raw payloads.
It retains expected/intersected/source-supported/valid areas, both fractions,
source-time presence and upstream_date_modified distinct from unknown historical
publication time. Day convention is the labeled 24-hour period ending in the
early morning, not midnight-calendar aggregation. TAVG remains NOAA supplied;
zero, negative temperatures and unavailable AK/HI are retained.

Verification uses offline labeled fixtures for positive/rejected metadata,
membership mutations and publish/rollback validation preceding pointer changes.
PR #549's full live proof contains COMPLETE observed/zero and out-of-coverage
unavailable only; partial/source-missing behavior remains fixture evidence.
No PROD write, source activation, new grant or historical ingestion is authorized.

Remaining deployment prerequisites: actual source-version and reviewed metadata
authority, exact target membership digest and retained capture proof, independent
review of validator/SQL diff, numbered migration reservation, effective owner and
intended API-reader proof. API #84 remains owned by its existing API agent.
