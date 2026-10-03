# Metadata after recorded acceptance

The DEV ledger now has two APPROVED_WITH_CONDITIONS decisions, linked to two
CONDITIONAL versions for the exact retained NOAA/Census inputs. The original
PENDING versions are preserved and both resources remain inactive. Independent
owner readback verified the full source-version/decision/artifact/resource/dataset
joins, four accepted revision hashes, and timestamp provenance.

The recording action occurred at `2026-10-03T03:38:53.059198Z`. The original
Matthew acceptance time remains UNKNOWN. A Snowflake session may display the same
instant in its local timezone; that rendering does not change the UTC instant.

`january-2025-recorded-metadata-candidate.json` retains the observed receipt and
four enriched metadata candidates with actual NOAA source-version identity.
The accepted definitions are unchanged. These are candidates, not publication
authority, and carry no scientific certification.
Revision 2 was created on October 3 and carries that actual metadata revision
date. Verification separately restores the accepted October 1 draft date solely
to reconstruct its original content hash; it never backdates the new revision.

The January-only optional `steward_review.acceptance_recorded_at` field preserves
`reviewed_at={state: UNKNOWN, value: null}`. It cannot be used for unrelated
measures, pending metadata, public scientific claims, or without the existing
exposure allowlist. Publication additionally reads both real owner decisions,
checks the actual decision/source-version binding and recording instant, and
reconstructs the original four accepted metadata content hashes. A copied
recording timestamp or changed definition cannot pass that check.

The full reviewed manifest still needs exact frozen capture membership/digest,
actual target payload reconstruction, genuine independent-review evidence and
current annual release preservation. DEV recording does not establish PROD
capture parity, view existence, grants or publication.

API #174 merged and deployed via release run 37093456657 at
`12511272ea45d09c7ffbb4936c430ac925ac9f57`; canonical smoke passed. The actual
safe startup event verified principal/reader-role/database/warehouse matches in
PROD. Both climate reads were `object_or_access_unavailable`; publication match
was false. That proves unusable service access, not object absence. No grant
was executed. Log access used the app UUID and exact deployment ID, avoiding app
specification lookup.
