# 0025: DEV PubMed/PMC Retrieval Corpus Versioning

Status: Accepted
Date: 2026-09-12
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

Approved PMC full-text artifacts and Neo4j extraction publications exist, but the
Research Assistant still lacked a Snowflake-backed, versioned retrieval corpus
that can be rebuilt deterministically with provenance and QC metrics. Neo4j
`EvidencePassage` nodes are not a rebuildable assistant corpus ledger.

## Decision

Own a DEV-only derived retrieval corpus in `one-health-lyme-gap-atlas-data`:

1. Eligibility requires `PAPERS.state = processed`, a recorded
   `final_review_decision_id`, an admitted `PMC_FULL_TEXT_ARTIFACTS` row, and a
   `GRAPH_PUBLICATION_RECEIPTS` contribution hash.
2. Chunking rules are versioned (`retrieval-corpus-v1`) and checksummed. Units
   are deterministic windows over JATS section text after open-access admission.
3. Corpus units are a rebuildable projection: a rules-version rebuild may delete
   and rewrite units for that version. Extraction attempt history remains
   append-only and is never rewritten by corpus builds.
4. Build runs and QC counters are queryable through
   `GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS`.
5. The CLI `pipeline build-retrieval-corpus` is DEV-only. No PROD promotion or
   unattended schedule is authorized by this ADR.

## Consequences

- Research Assistant corpus construction can proceed without coupling to Neo4j
  as the system of record for chunk identity.
- Operators can prove rebuild determinism via `corpus_content_sha256`.
- Later production corpus publication requires a separate ADR and promotion
  decision.

## Links

- Parent story: data repository issue #81
- Child: data repository issue #244
- Migration `V065__retrieval_corpus.sql`
- Workspace ADRs 0012, 0013, 0017
