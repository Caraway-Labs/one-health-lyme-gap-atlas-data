# 0023: DEV operator-captured restricted evidence

Status: Accepted
Date: 2026-09-09
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

ADR 0022 authorized GitHub to retrieve two pinned CDC files after the isolated
DigitalOcean runtime received repeated HTTP 403 responses. The GitHub-hosted
runner receives the same 403 response, while an operator's ordinary browser can
render the first-party page and download the workbook after presenting its data
use agreement.

The captured workbook says access is limited to the requestor, the raw data
should not be provided to other persons, derived publications must cite ArboNET,
and a final copy must be provided to CDC. It is therefore not appropriate to
treat the workbook as unrestricted public content. The operator also supplied a
browser-printed PDF of the landing page. That PDF preserves a human-reviewable
view but is not the publisher's original HTML and has no extractable text.

## Decision

Permit one DEV-only operator evidence transport for the already pinned CDC
county-status source. A repository-owned local CLI validates the PDF container,
the complete workbook package, the exact seven-column schema, ordered county
FIPS values, status vocabulary, and the embedded data-use and classification
terms. It then builds a short-lived private OCI envelope from the exact reviewed
DEV image and dispatches a protected GitHub workflow with only immutable
digests, a temporary tag, and a non-personal retrieval UUID.

The raw PDF and workbook never enter GitHub source, Actions artifacts, logs, or
a public registry. GitHub receives no Snowflake or Spaces credentials. The
temporary non-routable DigitalOcean job independently verifies every checksum,
the base and envelope digests, the retrieval UUID, exact source URLs, media
types, byte bounds, and manifest fields. It treats the PDF as opaque evidence
and does not render or execute it. Machine-verifiable source semantics come from
the workbook's embedded data-use agreement and classification sheets.

Only the runtime writes the files to private Spaces and appends DEV governance
evidence. The candidate remains `PENDING_REVIEW`; the steward must explicitly
decide permitted use, raw-access restrictions, attribution, delivery of a final
publication copy to CDC, and the meaning of `No records`. Raw artifacts must not
be exposed by Streamlit, the API, the public web application, logs, or workflow
artifacts.

The separately supplied pathogen-status workbook is excluded. Its seven
pathogen-presence fields are not `PATHOGEN_TESTING` observations because the
workbook supplies neither tested nor positive tick counts. It requires its own
source profile, a new canonical observation type or contract version, and a
separate steward decision.

## Consequences

The operator's workstation temporarily handles restricted raw files and must be
trusted for this one acquisition. The manifest records that no HTTP status,
ETag, or publisher `Last-Modified` value was observed; it must not manufacture
those values. File modification timestamps are retained only as local
acquisition evidence.

The PDF supports human review but cannot prove the publisher HTML byte-for-byte.
That limitation remains visible in the candidate. The workbook provides the
authoritative machine-checked terms and classification definitions.

## Alternatives considered

- Repeating the DigitalOcean or GitHub fetch was rejected after equivalent HTTP
  403 failures.
- Treating the browser print as first-party HTML was rejected because it would
  misstate provenance.
- Uploading the files to GitHub or a workflow artifact was rejected because the
  embedded agreement restricts redistribution.
- Combining the pathogen workbook with the tick-status source was rejected
  because the grains, semantics, and canonical requirements differ.
- Skipping the landing-page snapshot was rejected because the visible publisher
  context remains useful steward evidence even though the workbook contains the
  machine-verifiable terms.

## Acceptance criteria

- The local CLI fails closed on a changed workbook schema, invalid FIPS order,
  unreviewed status, unsafe XLSX member, changed embedded terms, malformed PDF,
  wrong base digest, or byte-bound violation.
- No raw source byte appears in Git, a GitHub artifact, or logs.
- The protected workflow verifies the temporary tag resolves to the supplied
  envelope digest, runs only in DEV, restores the exact prior topology, and
  removes the tag on success or failure.
- Runtime evidence distinguishes browser download/print from an observed HTTP
  200 response and retains the operator retrieval UUID.
- The candidate exposes the data-use restriction and publication obligations to
  the steward and creates no RAW, dbt, approval, PROD, or schedule mutation.
- The pathogen workbook remains outside this candidate.

## Rollout, observability, and rollback

Merge only after Python, workflow-policy, dbt-parse, and container gates pass.
Deploy the reviewed digest to DEV. Run the local CLI once with the supplied PDF
and county-status workbook. Correlate its retrieval UUID, envelope digest,
DigitalOcean deployment, ingestion run, requests, and retained artifacts.
Verify the prior DEV topology and zero temporary tags before steward review.

Rollback restores the exact prior app spec and deletes the short-lived tag.
Append-only failed-run evidence remains. A restoration or cleanup failure stops
all further pipeline work.

## Links to affected contracts and tests

- `docs/contracts/catalog-to-snowflake/requirements.md` FR-3.6 and FR-8.4
- `docs/contracts/catalog-to-snowflake/implementation-decisions.md`
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `docs/operations/cdc-tick-surveillance-dev-onboarding.md`
- `scripts/publish_tick_operator_evidence.py`
- `src/lyme_gap_atlas_data/tick_surveillance.py`
- `.github/workflows/capture-dev-cdc-tick-surveillance-operator.yml`
- `tests/test_tick_surveillance.py`
