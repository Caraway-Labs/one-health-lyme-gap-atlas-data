# Alpha parity baseline and comparison contract

This directory contains the immutable comparison contract for [#270](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/270).

`alpha-2026-08-06-baseline.json` is a metadata-only manifest of the retained
Alpha browser bundle. It contains field ownership, coverage, counts, value
states, score inputs, source metadata, and the SHA-256 of the original Alpha
bundle. It does not copy or mutate the Alpha POC database or redistribute raw
source files. The sidecar checksum binds the manifest bytes in this repository.

## Comparison rules

The governed semantic release is compared with all 3,144 Alpha county records,
unless a bounded comparison is explicitly documented with an omission and
follow-up owner. Compare, at minimum:

- county FIPS, names, state, contiguous-scope flag, and geometry;
- every analytical field and its null/value-state distribution;
- source contribution, vintage, source/retrieval metadata, and limitation text;
- score inputs, score output, methodology, and release identifiers; and
- row counts, duplicate FIPS, field types, and checksums.

Every difference must be classified as one of:

`SOURCE_REFRESH`, `SOURCE_REVISION`, `MISSINGNESS_VALUE_STATE`,
`GEOGRAPHY_SCOPE`, `GEOMETRY`, `METHODOLOGY`, or `DEFECT`.

An unclassified difference is a release blocker. An approved difference must
include the affected field/rows, evidence, expected user-visible effect, and
data steward, product owner, and engineering sign-off. The API must preserve
the Alpha release/methodology/provenance/limitation behavior unless a separate
approved API contract change says otherwise.

The public interpretation remains: published county-linked values are floors,
not true incidence; no records are not absence; ecological status is not
individual infection risk or diagnosis; and the score is a surveillance
follow-up priority, not a prediction or causal claim.

## Candidate evidence

Before publication, the parity command may read one named candidate release
using the existing protected migration connection and `--candidate`. It reads
only the candidate's semantic county, source-metadata, and release-metadata
relations; it produces the same metadata-only report and does not expose a
candidate through the browser or API. Public release comparison continues to
use the bounded current-release views.
