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
NOAA and TIGER resource/source-version/artifact/hash pins; a sorted immutable
`capture_ids` list; and `review_evidence` with
reviewed commit, actual GitHub review URL and reviewer. No invented approvals
or placeholder source-version IDs belong in an executable release manifest.
There is deliberately no sample manifest pretending to contain live approval.

Membership digest is SHA256 over UTF-8 lines of compact JSON arrays
`[capture_record_id, record_revision, record_id, source_row_hash, normalized_sha256]`,
ordered strictly by capture_record_id, one newline per tuple. All 389,856 selected
V103 revisions must match; no extra revisions in the selected run are accepted.
Both approved source versions must join their retained artifacts and this run.
Authority joins also bind the explicitly reviewed resource identity. NOAA uses
the existing source ID `noaa_nclimgrid_daily`, not an invented `source_` prefix.
Run completion, passing quality and native January resource/measure/normalization
and NOAA/TIGER hashes are rechecked at activation. Missing or inaccessible
authority fails closed. This does not transport DEV captures into PROD.

Header membership is not content proof. Activation rebuilds the entire target
candidate using PR #549's canonical partition parser, strict native-DOUBLE
reconciliation, original payload/source/normalization/revision hash checks and
scientific projector, then compares the recomputed candidate SHA256. Altering
payloads with unchanged ledger headers fails. Temporary candidates are removed.
The publication session must SELECT canonical normalized partitions as well as
revisions. V103 does not grant partition SELECT to the migration deployer;
missing access remains an explicit live gate. No role switch, secondary secret
connection or new grant is performed by this patch.

The frozen capture-ID list, rather than the whole run, defines view membership;
appending a run row does not add it to an already published release. At 64 hex
characters per ID, this list is approximately 26 MB of compact JSON. Verify the
target release VARIANT capacity and connector support before building a live
manifest; this draft does not claim that large-manifest round trip is proven.

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
`verified_climate_metadata_revisions` returns bounded authority only after full
verification. Pass it explicitly through `map_record`/`map_records`,
`validate_lineage` and `project_consumer`; default calls still reject exposure.
The existing lineage snapshot may name the approved 2025 TIGER input version
in the NOAA run's `input_source_versions` mapping. This narrowly scoped climate
case preserves primary NOAA run/source binding and artifact/record/input joins;
unrelated products retain original single-source run checks.

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
existing pointer rollback controls both annual and daily exposure. All seven
numeric quantities preserve native VARIANT storage and explicitly normalize JSON
null to SQL NULL. Each also has TYPEOF and guarded DOUBLE transport columns,
because VARIANT JSON can round DOUBLE but unconditional AS_DOUBLE can coerce
DECIMAL. `climate_numeric.decode_numeric_fields` recovers native DOUBLE and
exact Decimal/integer values and removes transport columns before API shaping.
No TO_JSON reconstruction or precision-reducing casts are used.
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

The offline harness executes the actual numeric SQL expressions with observed
DECIMAL-coercing AS_DOUBLE behavior, verifies SQL IS NULL/API JSON null and all
seven-field connector decoding, and executes the frozen capture join against an
appended same-run row. It is not Snowflake compilation proof. Before publication,
the reviewed SQL needs governed DEV verification of all storage types and nulls,
seven-field connector parity, view membership and rollback under intended roles.

Remaining deployment prerequisites: actual source-version and reviewed metadata
authority, exact target membership digest and retained capture proof, independent
review of validator/SQL diff, numbered migration reservation, effective owner and
intended API-reader proof, canonical partition read authority and large-manifest
round trip. API #84 remains owned by its existing API agent.
