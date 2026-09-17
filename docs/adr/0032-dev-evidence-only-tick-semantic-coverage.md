# 0032: DEV evidence-only tick semantic coverage

Status: Accepted
Date: 2026-09-17
Decision owner: Atlas product/data steward and engineering

## Context

ADR 0023 retains the CDC Ixodes county-status workbook as a restricted-egress,
evidence-only Tier D source. Its completed DEV evidence run proves publisher
context, artifact retention, terms, and source semantics, but intentionally
does not create routine RAW/STAGING/CONFORMED rows, quality results, or a
publication. Treating that evidence as a completed routine ingest would be
false. Omitting its source identity entirely would also conceal a material
Alpha-parity difference.

## Decision

The protected DEV semantic builder may use this source only after an
owner-recorded, source-version/run-pinned coverage classification. The V081
procedure is DEV-only, accepts only the completed
`cdc_tick_ixodes_county_status` evidence run, and records exactly 3,144
unresolved counties with `UNKNOWN_SOURCE_COVERAGE` and zero reported rows.

The semantic builder then renders `scapularis_status` and
`pacificus_status` as `Unknown` for every county, with the classification ID
in lineage. It never treats that classification as `No records`, absence,
quality success, source-native rows, or production approval. Routine sources
continue to require retained artifacts, blocking-quality proof, staged
publication, and retrieval evidence.

## Consequences

- The candidate release can transparently represent the restricted-source
  parity exception without fabricating tick observations.
- The release remains a DEV candidate until the later parity review explicitly
  accepts or rejects this difference; V081 grants neither public publication
  nor Tier C/PROD authority.
- A future permitted row-level transport requires a new approved source-native
  mapping and supersedes this all-unknown exception rather than mutating it.

## Acceptance criteria

- The exception is limited to the exact approved tick resource, DEV database,
  completed run, and all-unknown 3,144-county classification.
- Semantic lineage identifies the classification for every synthesized unknown
  tick observation.
- `No records` is never generated from the exception.
- No restricted source bytes or source rows enter Git, CI artifacts, API, web,
  or PROD through this decision.

## Rollout and rollback

Deploy V081 through the protected DEV migration path. The steward records the
classification with a rationale; the protected semantic build then produces a
candidate only. Rollback is a forward-only revocation of procedure usage; the
immutable classification and candidate remain auditable.

## Links

- ADR 0023
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `docs/contracts/semantic-release/README.md`
- `migrations/V081__dev_evidence_only_tick_coverage_classification.sql`
