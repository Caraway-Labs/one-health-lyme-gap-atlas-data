# x5j9 record identity and revision policy

Status: Accepted for the bounded #252 parity work  
Date: 2026-09-14  
Owner: Atlas data and engineering

This policy resolves the record-identity question from [#279](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/279) without inventing a natural key from county, year, case status, sex, age, or frequency fields.

## Bounded source evidence

On 2026-09-15T05:57:52Z, a read-only request was made to the first-party Socrata metadata and data endpoints:

- Metadata: `https://data.cdc.gov/api/views/x5j9-wybp`
- Sample query: `$select=:id,:created_at,:updated_at,year,fips,case_status,frequency`, `$limit=25`, `$order=:id ASC`
- Metadata response SHA-256: `6086dde4d2dade7d53ff20a4e5949607f55101d4c9c88f96a9161cce1e2f0386`
- Sample response SHA-256: `a1bea06167218bed2db981abc26f8df0d4c603bca698bb1ddb774c4af2a59bdb`

The metadata identified dataset `x5j9-wybp`, seven source columns, and the title “Lyme disease public use aggregated data with geography, 2022-2023”. The bounded sample contained 25 rows, 25 distinct Socrata `:id` values, and no duplicate IDs. It also exposed `:created_at` and `:updated_at` values for the sampled records. The dataset-level `rowsUpdatedAt` was 2025-08-19T18:35:15Z and `viewLastModified` was 2026-09-10T00:08:37Z.

The evidence confirms that a publisher system ID is available when the system column is explicitly selected. It does not prove that an ID remains unchanged through an unobserved publisher revision because the public endpoint does not provide a revision history. That limitation is retained in the policy and parity report.

## Decision

1. The Socrata adapter requests `:id`, `:created_at`, and `:updated_at` alongside the source columns. These system fields are retained in the source-faithful payload and are not treated as analytical measures.
2. When `:id` is present and non-empty, the governed `source_record_id` is that publisher ID. A change to the row contents therefore updates the same governed record ID while changing its source-row checksum.
3. A plain `id` is accepted only as a compatibility fallback for fixtures or a source that explicitly exposes that field. It is not synthesized by Atlas.
4. When no publisher ID is present, `source_record_id` remains null and the governed record ID uses the canonical full-row SHA-256. This is an identity limitation, not a natural key. A later row revision becomes a new content-identified record; publication must not silently overwrite the prior record.
5. The row checksum includes all retained source fields, including publisher revision timestamps. It is used to detect revisions and preserve immutable lineage, not to replace the publisher identity.
6. Duplicate publisher IDs in one acquired payload are a schema/quality failure candidate. Duplicate full-row hashes are retained as an explicit duplicate observation and are not collapsed by a demographic tuple.

## Operational consequences

The policy is compatible with source-faithful artifacts, V069 idempotent merges, V070 fresh-process resume, and Alpha parity comparison. A parity comparison must report whether identity came from a publisher ID or the content-hash fallback and must not claim revision reconciliation where no publisher revision history exists.

The policy does not authorize a full acquisition, production release, API cutover, or mutation of the Alpha POC. Those actions remain governed by #270, #255, #274, #273, #276, and #277.

## Test and review links

- Implementation: `src/lyme_gap_atlas_data/ingestion/identity.py`
- Runtime use: `src/lyme_gap_atlas_data/ingestion/runtime.py`
- Socrata system-field retention: `src/lyme_gap_atlas_data/ingestion/adapters.py`
- Tests: `tests/test_pipeline_simplification_phase2.py`
- Contract: `docs/contracts/simplified-ingestion/interface-freeze.md`
