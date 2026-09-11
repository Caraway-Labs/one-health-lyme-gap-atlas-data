# Data Pipeline Instructions

Read the workspace `TECHNOLOGY_AND_GOVERNANCE.md`, ADR 0005, and the governed
contracts in `docs/contracts/catalog-to-snowflake/` before changing pipeline
code, Snowflake DDL, source configuration, or deployment files.

- This repository owns the governed ingestion pipeline, dbt project, Snowflake
  Streamlit approval console, and its DEV/PROD deployment assets.
- Never modify or load the Alpha POC database `ONE_HEALTH_LYME_GAP_ATLAS` from
  governed pipeline commands. Use the suffixed DEV/PROD databases only.
- Preserve append-only provenance, source-faithful RAW payloads, and the
  distinction between zero, null, unknown, suppressed, and not-reported.
- Full acquisition requires an approved source version; a pipeline runtime role
  must never approve candidates.
- Commit blank environment templates only. Do not log credentials, artifact
  contents, or unredacted request data.
- For Codex-initiated Snowflake inspection or administration, use `snow` with
  the local `BVB26657_PAT` named PAT connection. First run a bounded read-only
  query that reports the effective user, role, database, and warehouse. A
  missing or expired PAT is a blocker; never trigger an interactive browser
  login as a substitute.
- Use a DEV, least-privilege connection by default. Production, migrations,
  roles/grants, and other privilege changes require explicit user scope and
  authorization for that specific action.
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`,
  `uv run pytest`, `dbt parse`, and the container build for material changes.
