# 0029: CDC pathogen-status restricted ingress

Status: Accepted
Date: 2026-09-16
Decision owner: Atlas product/data steward and engineering

## Context

The CDC ArboNET Tick Module workbook *Tickborne Pathogens Identified in
Host-Seeking Ixodes spp. Ticks: Status by Contiguous United States County
(through Dec. 31, 2025)* is distinct from the county-status workbook covered
by ADR 0023. It supplies seven county/pathogen status and source pairs, but no
tested-tick counts, positive-tick counts, sampling effort, or laboratory-method
detail.

The product/data steward downloaded the workbook from the CDC Tick Surveillance
Data Sets page, accepted the displayed terms, and on 2026-09-16 authorized a
restricted governed ingestion path. The terms state that access is limited to
the requestor, raw data should not be provided to others, derived
publications/presentations must cite ArboNET, and CDC Division of Vector-Borne
Diseases must receive a final copy of resulting publications/presentations.

## Decision

Use `PATHOGEN_PRESENCE_STATUS` in the canonical tick-surveillance v1 contract
for this source. `Present` and `No records` are cumulative published-record
statuses, not test results. `No records` must never be represented as pathogen
absence, a negative test, prevalence, human disease incidence, individual risk,
or diagnosis.

The source is Tier D/restricted. Its raw workbook moves only through a
requestor-controlled, short-lived private evidence envelope and named private
governed storage. Raw bytes must not enter Git, GitHub Actions artifacts,
workflow logs, public registries, Streamlit, API responses, or public web
delivery. Source and release provenance must cite the CDC dataset landing page
and attribute the CDC ArboNET Tick Module. The final-copy obligation remains
an operational release requirement before any resulting publication or
presentation is externally finalized.

This ADR records the product/data-steward decision and technical controls; it
does not provide a legal interpretation of CDC terms. A bounded DEV evidence
proof is authorized. A production write, public semantic release, or recurring
acquisition remains subject to separate protected Tier C approval.

## Consequences

- The existing operator-envelope workflow now accepts an explicit, validated
  `pathogen` profile alongside its original `tick` profile. The profile input,
  short-lived registry tag, manifest endpoint, parser, and temporary runtime
  command must agree; a county-status bundle cannot be processed as pathogen
  evidence or vice versa.
- The source obtains a separate profile, parser, quality tests, and evidence
  identity. It cannot be inferred from the tick county-status workbook.
- Public provenance can describe the source and limitations without exposing
  raw workbook content or source-level data beyond the separately approved
  semantic release.
- Seven pathogen fields remain available for governed mapping, while the
  Alpha-equivalent *Borrelia burgdorferi sensu stricto* field receives an
  explicit 3,144-county parity classification before release.

## Alternatives considered

- Reusing `PATHOGEN_TESTING` was rejected because the workbook has no test or
  positive counts and would create a false prevalence implication.
- Reusing the county-status evidence envelope without source-specific
  validation was rejected because its schema and semantics differ.
- Committing, attaching, or publicly hosting the workbook was rejected because
  it violates the recorded restricted handling boundary.
- Treating `No records` as absence was rejected because it contradicts the
  publisher's classification terms.

## Acceptance criteria

- The source profile is DEV-only and `EVIDENCE_ONLY`.
- Validation fails on a changed workbook schema, invalid/out-of-order FIPS,
  unreviewed status, unsafe XLSX member, or changed embedded terms.
- Validation separately counts blank FIPS rows and preserves their parity
  implications rather than silently treating them as counties.
- Canonical pathogen status records require pathogen, status, and cumulative
  time semantics, and cannot populate testing/prevalence fields.
- The private evidence workflow runs only after the reviewed image reaches DEV
  and leaves immutable DEV lineage plus a pending steward candidate.
- No PROD semantic release occurs without protected Tier C approval and full
  release/parity evidence.

## Rollout, observability, and rollback

Merge the source profile, parser, contract, and synthetic tests through the
standard quality gate. Deploy the reviewed image to DEV. The operator envelope
will record its retrieval UUID, source checksum, image digests, and resulting
DEV evidence identifiers. Rollback restores the prior DEV topology and removes
the temporary tag; append-only artifacts and failed evidence remain retained.

## Links to affected contracts and tests

- `config/sources/cdc_tick_ixodes_pathogen_status.yml`
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `src/lyme_gap_atlas_data/pathogen_surveillance.py`
- `tests/test_pathogen_surveillance.py`
- `docs/operations/cdc-ixodes-pathogen-source-review.md`
