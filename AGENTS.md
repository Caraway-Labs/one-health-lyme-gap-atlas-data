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
- The existing DEV PMC worker is the non-routable DigitalOcean droplet
  `oh-lyme-dev-pmc-extraction`; use its systemd service
  `oh-lyme-pmc-extraction.service` only after the protected `deploy-dev.yml`
  workflow has applied the relevant migration. Do not create a second worker,
  use production configuration, or copy secrets between environments.
- For PMC runtime verification, first inspect the approved paper and migration
  ledger through `ATLAS_DEV_PMC_AUDIT`, then run at most the owner-approved
  bounded service invocation. Verify afterward that OAI-PMH retrieval,
  budget reservation, redacted artifacts, extraction attempts, and graph
  receipts each have the expected ledger evidence. A failed budget reservation
  is fail-closed evidence, never a reason to bypass the procedure.
- Owner-rights procedures need a dedicated least-privilege owner with direct
  grants on only their dependencies; runtime roles receive procedure `USAGE`,
  never direct table access. For the PMC budget procedure, follow the V056/V057
  bootstrap in `docs/operations/deployment-promotion.md` and retain both API
  and pipeline procedure grants after `CREATE OR REPLACE`.
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`,
  `uv run pytest`, `dbt parse`, and the container build for material changes.
- PMC retries: the three-failure ceiling applies only to confirmed LLM
  execution failures. Record provider rejections before inference in an
  append-only classification ledger; reopen an exhausted DEV paper only via
  the reviewed recovery procedure and a state event, never by editing history.
