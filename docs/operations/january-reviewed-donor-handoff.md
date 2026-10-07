# January 2025 reviewed annual donor handoff

This corrects the DATA #443 diagnostic role/query mismatch without granting the
ingestion runtime access to release base tables. The previous failure established
an object-or-access error, not object absence. Product approval covers January
county weather engineering; it does not establish technical donor provenance.

## Producer and independent review

`climate_membership.export_donor_handoff(cursor, output, code_sha)` is a SELECT-only
helper for the existing protected DEV migration-deployer service identity. It
opens no connection and runs no migration, grant, publication or source download.
It verifies the effective user/role/database and a nonempty warehouse, reads the
published ATLAS donor and bundle digest, validates all five annual source slots,
and compares the donor to `CURRENT_RELEASE_V` before atomically writing JSON.
The artifact omits user, account and warehouse identifiers.

The helper is deliberately not wired to a new unbounded workflow. Before any
live producer execution, review a bounded invocation under the existing protected
DEV release operator, its exact reviewed code SHA, timeout/no-retry controls,
warehouse identity/settings and full cost ceiling. Do not invoke the existing
publish operation to obtain this artifact: it can apply migrations and publish.
A caller must enforce its separately reviewed session and cleanup limits.

Retain the actual protected run receipt and independently review its successful
identity checks, code SHA, artifact digest, and full manifest. A JSON role string
and hash alone do not authenticate the producer. Never manufacture this artifact
from a fixture or infer its contents from a failed query. Commit the actual,
reviewed safe JSON under `docs/contracts/climate/reviewed-donors/` in a reviewed
PR; do not commit credentials or private operational receipts. No such live
artifact is included in this change.

## Runtime consumption

The existing frozen-membership operation accepts `january_donor_handoff_path`
and `january_donor_handoff_sha256`. Independent review must bind both inputs to
the protected producer run and reviewed producer commit. Missing inputs, paths
outside the approved directory (including resolved symlink escapes), files over
64 KiB, digest mismatch, unknown fields, invalid/future timestamps and invalid
annual manifests fail closed before connection.

The ingestion runtime reads only the intended current-release view for donor
verification. Release ID and bundle hash must equal the reviewed artifact both
before and after the ordered capture export. Missing, duplicate, changed or
inaccessible view rows block the export. The full existing annual-manifest
validation, selected-run/input hashes, row-count checks, capture digest and
atomic output replacement remain required. This artifact is a read-only candidate,
not an approval, publication, DEV acceptance or API acceptance.

## Cost and future execution proposal (not approved)

Carry forward the full consumed forecast reservation of $6.836666666666667 against
the approved $7 total cap. Actual invoiced charges remain unknown. The remaining
$0.163333333333333 does not authorize either live donor read or another export.
The checked-in guard consequently rejects another forecast before connecting.

A future proposal must cover both producer and consumer, connection time,
warehouse resume/minimum billing, cancel/cleanup, cloud services and failed attempts.
An illustrative ceiling, only if both reviewed warehouses are Standard,
single-cluster Gen2 XS at the verified public $6/credit ceiling, is:

- Producer: 15 seconds bounded execution plus 15-second cleanup, with the
  60-second warehouse minimum and cloud-service allowance (1.35/30 credits):
  `(60 * 5.75 / 3600 + 1.35 / 30) * 6 = $0.845`.
- Consumer: 50 seconds plus 15-second cleanup and the same allowance:
  `(65 * 5.75 / 3600 + 1.35 / 30) * 6 = $0.892916666666667`.
- Additional shared billing uncertainty reserve: $1.
- Combined additional reservation: $2.737916666666667; prior plus proposal:
  **$9.574583333333334**, so a proposed **$10 total cap** would cover this
  illustrative pair. This is a proposal, not authorization or invoice evidence.

Do not execute until Matthew approves a specific finite revised cap and the
independent review verifies both actual warehouse configurations, the protected
producer path and complete bounded invocation. Retain failed-attempt reservations;
do not reclaim them from short elapsed time. A fresh approved cap requires a
separately reviewed guard update. A 50-second export may still be insufficient;
stop and retain the blocked receipt rather than retrying automatically.

No new grant, credential setting, warehouse configuration, PROD publication or
historical expansion is authorized by this correction. DEV donor/membership
proof, modeling, governed publication and the dependent API acceptance remain
separate downstream gates.
