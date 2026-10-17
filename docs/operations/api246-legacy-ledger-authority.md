# API #246 exact historical PROD ledger recognition

Decision date: **2026-10-17**. Owner: the actual product and release owner,
directly authorizing the decision in the API #246 conversation. Durable record:
https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-api/issues/246#issuecomment-6240165767

This new decision recognizes the exact two retained V071 ledger records solely
for compatibility validation. It does not assert that the second historical
execution was independently authorized or successfully performed. It authorizes
no history edit, replay, production write, merge, deployment or steward action.

## Existing authority and evidence

V020's authority is the applied historical V022 migration from commit
`06488072908e8fd4c68901ce0a22e45416eec38f`. Its source explicitly preserves
the two immutable V020 records and checks their count and identical checksum.
The retained PROD V022 reconciliation binds that historical variant to current
source. V028 retains its existing exact two-row exception and immutable PROD
reconciliation. Both V022/V028 reconciliation receipts remain mandatory and
must be unique and match the pinned legacy/current checksums.

V071's implementation was reviewed in Data #285. Data #286 and the semantic
release runbook preserve its history and document the bootstrap boundary.
Those records do not supply a duplicate-recognition decision. The owner supplied
the new present-dated recognition above after the missing authority was reported.
The reason for the second V071 registration remains unverified.

Bounded read-only PROD evidence verified actual user MATTHEWCARAWAY, role
OH_LYME_PROD_MIGRATION_DEPLOYER, PROD database, OH_LYME_PROD_APPROVAL_XS_WH and
empty secondary roles before inspecting the retained ledger. The six exact
records are retained in the packaged `cdc_legacy_ledger_authority.json`, including
original filenames, checksums, deployment commits, actors and UTC timestamps.
These are migration metadata; no private scientific source identities are added.

## Narrow validation

The CDC-only driver requires the immutable reviewed authority file to match its
pinned SHA256 after normalizing text line endings. Missing/changed authority
fails closed. It checks the actual V020/V028/V071 rows against all six identities,
including full stored UTC timestamp precision, and cross-checks their version/checksum
projection against the first complete ledger read. Both identical timestamps
substituted for the distinct original timestamps, excess/missing entries,
different filenames/commits/actors/checksums and unrelated duplicates all fail.

The V022/V028 legacy source reconciliation is still validated separately. No
new database receipt is invented or registered. V071's authority is the new
reviewed owner decision retained with the versioned implementation; its scope
does not rewrite or backdate any original receipt. Changes to this authority
require another reviewed decision and implementation, never a mutable runtime
configuration override. Non-CDC migration behavior remains unchanged.

V156 must still have exactly one same-reviewed-commit/checksum/filename receipt
for an already-applied retry. The complete pending set is checked again; V150
must remain pending. Existing role, grants and exact current-release pointer
checks remain. Initial application runs only V156; recovery never replays it
or registers stewardship decisions. No migration SQL, grant, scientific meaning,
CDC packet, revision-3 metadata, donor receipt or API contract changes.

## Release and recovery

Obtain independent exact-commit review, green full hosted Quality and explicit
human merge approval. After merge, use the existing protected DEV/image proof
and record its exact immutable digest and source SHA. Revalidate actual historical
ledger and pending V150/V156 metadata before preparing `promote-prod.yml` with
`cdc_admission_only=true`; do not use the superseded Data #697 driver image.
Production execution requires separate approval. Follow
[the existing CDC runbook](api246-cdc-restoration.md) for all exact workflow
inputs, protected full-view/procedure checks, separately approved real human
non-Streamlit registration, actual consumer readback and later API acceptance.

On image failure after a successful V156 receipt, rerun the same protected
source SHA/digest with the original reviewed pending inputs, or the reviewed
V150-only set. Every guard runs again. Preserve historical rows and V150; stop
for changed identity, grant, pointer, digest or receipt. Partial DDL without a
receipt still requires protected inspection. No production operation is executed
as part of this hotfix PR. API #249 stays held until Data acceptance.
