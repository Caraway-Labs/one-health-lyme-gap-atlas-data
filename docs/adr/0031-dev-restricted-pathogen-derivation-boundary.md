# 0031: DEV restricted pathogen derivation boundary

Status: Accepted
Date: 2026-09-17
Decision owner: Atlas product/data steward and engineering

## Context

ADR 0029 approved private DEV evidence capture for the requestor-restricted CDC
ArboNET pathogen workbook.  The source steward has now authorized a bounded
private DEV derivation path so the approved county-status output can be
evaluated for the Epic #252 semantic release.  The generic ingestion tables
are not a suitable boundary: their routine runtime grants intentionally serve
unrestricted SourceDefinition ingestion.

The workbook remains restricted.  Its county/pathogen status fields are not
testing, prevalence, absence, incidence, individual risk, or diagnosis.  The
reviewed source covers 3,111 valid FIPS rows plus six blank-FIPS rows, while
the semantic release requires 3,144 county identities.  Missing source rows
must remain a parity finding rather than being silently converted to `No
records`.

## Decision

Create a DEV-only, source-specific RAW -> STAGING -> CONFORMED boundary owned
by an owner-rights procedure.  The existing DEV runtime receives `USAGE` on
that procedure only; it receives no direct privilege on any restricted table.
It submits parameter-bound, validated workbook rows from the short-lived
private operator envelope.  The procedure validates the approved source
version and retained evidence artifact, stores source-faithful restricted rows
in RAW and normalized restricted rows in STAGING, and emits a conformed table
containing only the derived *B. burgdorferi sensu stricto* county status,
source-row lineage, and `REPORTED` coverage state.

The procedure records immutable run, quality, request, and staged-publication
lineage.  Its staged output is eligible only for a later protected semantic
candidate; it is not an API, Streamlit, or public-web relation.  No table in
the boundary is granted to the API, read, Streamlit, or routine runtime role.

The semantic builder reads the dedicated conformed relation for the pathogen
slot.  It fails closed unless it has explicit coverage for every canonical
county.  A parity report therefore remains required to classify the 33 county
identity difference before any semantic release or Tier C promotion.

## Consequences

- This is a documented Tier D exception, not a change to generic Tier B/C
  ingestion or a new runtime role.
- Restricted values are visible only to the private envelope process and the
  owner-rights procedure.  Bound parameters must never be printed or logged.
- A full DEV derivation can be repeated from a checksum-bound evidence run;
  it cannot run in PROD and does not create a schedule.
- CDC ArboNET attribution and the final-copy obligation remain release gates.

## Alternatives considered

- Using generic governed-source tables was rejected because the runtime has
  direct table access there.
- Treating source omissions as `No records` was rejected because it would
  erase a material geography/parity distinction.
- Granting direct restricted-table access to the runtime was rejected because
  it would broaden the source restriction boundary.

## Acceptance criteria

- The migration is DEV-only and grants procedure `USAGE`, never restricted
  table access, to the runtime role.
- The loader validates the private bundle and source semantics before it binds
  any row payload to Snowflake.
- RAW and STAGING retain no public grant; CONFORMED retains only the approved
  derived county-status projection and lineage.
- The procedure rejects an unapproved source version, mismatched evidence
  checksum, invalid row set, duplicate FIPS, invalid status, or non-DEV use.
- Missing county identities block semantic assembly pending an explicit parity
  classification.

## Rollout, observability, and rollback

Deploy through the protected DEV migration workflow, then run the private
operator-envelope evidence capture followed by the private derivation command
using its returned evidence run ID.  Verify only aggregate lineage, quality,
and parity counts through the owner-controlled views; do not export rows.
Rollback disables further derivations by revoking procedure usage in a new
approved migration.  Retained restricted evidence and append-only run history
are not deleted.

## Links

- ADR 0023 and ADR 0029
- `docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.md`
- `docs/contracts/semantic-release/README.md`
- `migrations/V077__dev_restricted_pathogen_derivation_boundary.sql`
- `src/lyme_gap_atlas_data/pathogen_surveillance.py`
