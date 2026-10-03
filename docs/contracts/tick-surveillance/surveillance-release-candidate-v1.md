# Surveillance release candidate v1

Story #439, parent #436. This is the deterministic preparation contract for a
governed coverage/priority release. It is not a publication receipt or a new
methodology. `build_surveillance_release_candidate` has no I/O or runtime callers.

## Scope and version binding

Inputs are #171 calculator envelopes, an explicit evidence basis, a safe release
ID and scope reference, and a nonempty manifest of exact expected coverage result
IDs. The builder reuses the approved v2 coverage serializer and computes each
triage projection with the #172 evaluator and serializer. Callers cannot supply
their own priority, score, rank, changed coverage interpretation or publication
status. Candidate membership must match exactly: missing, extra, duplicate or
changed-revision results fail closed. Membership says nothing about completeness
of a publisher's underlying universe.

The canonical JSON SHA-256 binds contract version, release identity, scope,
ordered membership, exact projections and evidence basis. Input arrival order
does not affect the digest. A change in any bound fact creates another snapshot;
a future immutable writer must reject reuse of a release ID with a different
digest, serialize writers and verify persisted bytes. This module does not
provide that writer or claim a Snowflake primary key enforces uniqueness.

## Consumer semantics

Each coverage and priority document is retained unchanged from its established
serializer, including source version/vintage, snapshot and omission references,
geography/time, reason codes, quality, safe lineage, representativeness and
categorical state. Priority keeps its separate comparison cohorts and unordered
tie groups; canonical result-ID ordering is transport ordering, never ranking.
There is no disease-risk, absence, county-wide site generalization, automatic
allocation or numeric priority score. Unknown and unavailable evidence remain
admissible as explicitly limited evidence, never as positive coverage.

Existing complete publisher-scoped snapshot requirements still govern omission
and county representation. A complete candidate manifest cannot authorize an
omission claim when that source proof is missing. Synthetic results remain
synthetic. `CURRENT_CODE_SOURCE_BACKED_REPLAY` remains the caller's declared
evidence basis, not proof supplied by this builder that replay occurred.

## Preparation and promotion are separate

The outer status is `CANDIDATE_NOT_PUBLISHED`; inner documents remain
`INTERNAL_DEV_ONLY`. The wrapper provides a release identity without changing
the meaning or authorization of immutable historical results.

Normal promotion must bind this exact digest to retained, source-backed replay
and source approval evidence, reviewed scope and limitations, an immutable
artifact, the protected PROD release receipt, and intended-role readback. It
must fail closed if any required receipt is absent or references different
bytes. Fixtures can prove implementation, but cannot satisfy live promotion
proof. No candidate builder output alone may become a public current pointer.
Historical releases remain immutable; rollback selects a previously accepted
snapshot rather than modifying evidence. No pointer, migration, grant or writer
is added by this preparation slice.

Existing API #94 owns the planning-evidence exposure path, with Data #441 owning
request-package compatibility. API must retrieve an accepted release-pinned
projection and preserve its fields; it must not recalculate triage. API #88 owns
the related general evidence-state metadata. This contract adds no WEB work.

## Acceptance mapping and remaining delivery

- Versioned release preparation and exact revision binding are implemented.
- Consumer projections preserve the existing approved semantics and limitations.
- Tests cover incomplete manifests, changed evidence, source omission without
  complete proof, synthetic evidence and unchanged categorical triage.
- Live artifact retention, immutable writer/readback, protected promotion and
  actual API consumer acceptance remain unimplemented follow-through for #439
  and #436. Neither story nor epic should close on this candidate slice alone.
