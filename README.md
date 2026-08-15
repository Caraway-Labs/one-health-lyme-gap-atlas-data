# one-health-lyme-gap-atlas-data

Idempotent Snowflake provisioning and loading for the exact Alpha release.

```powershell
uv sync --extra dev
uv run atlas-data provision --dry-run
uv run atlas-data load --release alpha-2026-08-06 --dry-run
uv run pytest
```

Production mutations are intentionally local/manual for this MVP. GitHub CI
validates code, DDL, checksum, and the 3,144-county contract but never receives
Snowflake credentials or runs DDL/DML.
