# one-health-lyme-gap-atlas-data

The repository contains two deliberately separate capabilities:

- **Alpha POC loader:** idempotent provisioning/loading for the current exact
  release; it continues to support the existing API and is not migrated.
- **Governed pipeline:** catalog discovery, source approval, immutable
  artifacts, provenance, source-faithful RAW loading, and dbt through
  `CONFORMED` in `ONE_HEALTH_LYME_GAP_ATLAS_DEV`.

The governed pipeline contract is in `docs/contracts/catalog-to-snowflake/`.
See workspace ADR 0005 before provisioning it.

```powershell
uv sync --extra dev
uv run atlas-data provision --dry-run
uv run atlas-data load --release alpha-2026-08-06 --dry-run
uv run pytest
uv run atlas-data pipeline preflight
```

`pipeline preflight` is non-mutating: it checks the private Spaces bucket,
makes one metadata request per enabled catalog capability, and verifies the
dedicated pipeline service account's isolated DEV context. It does not crawl a
catalog, ingest data, or expose credentials.

The scheduled `pipeline discover` job runs the versioned catalog terms and
stores each catalog response as a private, content-addressed artifact with
append-only Snowflake request/run lineage. It discovers metadata only; full
source ingestion remains blocked pending a steward decision.

Production mutations are intentionally local/manual for this MVP. GitHub CI
validates code, DDL, checksum, and the 3,144-county contract but never receives
Snowflake credentials or runs DDL/DML.
