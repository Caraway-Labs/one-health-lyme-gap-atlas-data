# 0026: PROD Retrieval Corpus Publication and Citation Provenance Lookup

Status: Accepted
Date: 2026-09-13
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

ADR 0025 authorized a DEV-only derived retrieval corpus. Evidence Chat still
retrieves from Neo4j `EvidencePassage` nodes (ADR 0007). Operators now need the
same corpus tables in PROD and a procedure-only API path to enrich citations
with corpus provenance by PMID without replacing the Neo4j fail-closed gate.

## Decision

1. Publish `RETRIEVAL_CORPUS_BUILDS` / `RETRIEVAL_CORPUS_UNITS` in both DEV and
   PROD via env-neutral migration V066 (CREATE IF NOT EXISTS; pipeline
   `{{ ENV }}` grants). Do not create account roles in V066; DEV auditor SELECT
   remains from V065, and PROD auditor SELECT waits on out-of-band role
   provision.
2. Allow operator corpus rebuilds in PROD when `TOPX_ENV=prod` and
   `ENABLE_PRODUCTION_EXECUTION=true`. No unattended PROD corpus schedule.
3. Expose `GOVERNANCE.SP_LOOKUP_RETRIEVAL_CORPUS_PROVENANCE(ARRAY)` to
   `OH_LYME_{{ ENV }}_API_RUNTIME` for bounded PMID lookups. The procedure
   returns unit ids, section labels, rules version, and artifact hashes only—
   not full unit text.
4. Citation enrichment is best-effort: missing corpus rows or lookup failures
   must not fail a Neo4j-grounded chat turn.
5. Supersede ADR 0025’s “DEV-only / no PROD” publication limit for tables and
   operator rebuild. Attempt-history immutability is unchanged.

## Consequences

- PROD may have zero units until processed papers and artifacts exist there.
- API OpenAPI may add optional citation provenance fields.
- Image promotion remains digest-identical DEV→PROD (ADR 0006).

## Links

- ADR 0025 (DEV corpus versioning)
- Workspace ADR 0007 (Neo4j evidence gate)
- Workspace ADR 0019 (enrichment does not replace Neo4j gate)
- Migration `V066__retrieval_corpus_prod_and_api_lookup.sql`
- Issues #81 / #244
