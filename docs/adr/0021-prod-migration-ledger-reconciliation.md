# 0021: Canonical migration checksums and pinned PROD reconciliation

Status: Accepted
Date: 2026-09-08
Decision owner: Atlas owner

## Context

The protected `qtbi-xd4i` PROD rollout halted before V051 because 13 ledger
rows across 12 versions did not equal the current source hashes. Eleven
versions were byte-for-byte equivalent after normalizing LF versus CRLF. The
applied PROD V022 source is a historical variant that validated duplicate V020
rows, while the later repository source validates DEV's duplicate V019 rows.
PROD also has exactly two identical V028 rows. No V051 or V052 DDL ran.

## Decision

Migration validation recognizes LF and CRLF hashes as equivalent only when both
derive from the same normalized SQL source. All other content changes remain
blocking.

Add an explicit PROD-only reconciliation command pinned to the observed V022
and V028 filenames, checksums, and row counts. It creates or verifies an
append-only `GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS` record and never
updates or deletes `SCHEMA_MIGRATIONS`. The command is manual, requires
confirmation and separately authorized elevated execution, and is excluded
from routine DEV deployment.

V051 continues to require its own one-time AccountAdmin authorization. V052
uses a distinct PAT restricted to `OH_LYME_PROD_GOVERNED_VIEW_OWNER`; a
role-restricted AccountAdmin PAT is not weakened or reused.

## Consequences

Cross-platform line-ending serialization no longer creates false checksum
drift. The V022 content difference and duplicate V028 evidence remain explicit,
environment-scoped, and reviewable. Any unlisted version, changed content,
unexpected filename, unexpected count, or conflicting reconciliation record
still halts promotion.

## Alternatives considered

Rewriting legacy ledger hashes or deleting duplicate rows was rejected because
it would destroy immutable deployment evidence. Ignoring all line-ending
differences or globally allowing historical checksums was rejected because it
would weaken tamper detection. Reusing AccountAdmin for V052 was rejected
because it violates the governed-view ownership boundary.

## Acceptance criteria

- Only LF/CRLF serialization of identical SQL is checksum-equivalent.
- The PROD reconciliation accepts exactly one pinned V022 row and two identical
  pinned V028 rows.
- Reconciliation evidence is append-only and scoped to PROD.
- The routine DEV workflow never invokes the PROD reconciliation.
- V051 and V052 retain their distinct execution-role requirements.

## Rollout, observability, and rollback

Merge only after repository gates. Deploy the image to DEV and promote the
same digest to PROD. With separate authorization, run the PROD reconciliation
and verify its two evidence rows. Then apply and ledger V051 as AccountAdmin,
end that session, and apply V052 through the governed-view-owner PAT. A failure
leaves original migration history intact; omit later steps until the mismatch
is resolved rather than editing the ledger.

## Links

- ADR 0020
- `docs/operations/deployment-promotion.md`
- `docs/operations/cdc-historical-prod-ingestion.md`
- `src/lyme_gap_atlas_data/migrations.py`
- `tests/test_governed_pipeline.py`
