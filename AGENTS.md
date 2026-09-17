# Data Pipeline Instructions

Read the workspace `TECHNOLOGY_AND_GOVERNANCE.md`, ADR 0005 (amended by data
ADR 0027), `docs/contracts/catalog-to-snowflake/operating-model.md`, and
`docs/contracts/simplified-ingestion/interface-freeze.md` before changing
pipeline code, Snowflake DDL, source configuration, or deployment files.

- This repository owns the governed ingestion pipeline, dbt project, Snowflake
  Streamlit approval console, and its DEV/PROD deployment assets.
- Never modify or load the Alpha POC database `ONE_HEALTH_LYME_GAP_ATLAS` from
  governed pipeline commands. Use the suffixed DEV/PROD databases only.
- Preserve append-only provenance, source-faithful RAW payloads, and the
  distinction between zero, null, unknown, suppressed, and not-reported.
- Tiered governance (ADR 0027): Tier A local/fixture; Tier B routine DEV public
  sources advance via automated checks without a steward click solely to unlock
  technical stages; Tier C PROD remains protected; Tier D exceptional/restricted
  sources still require Streamlit steward review. A pipeline runtime role must
  never approve candidates.
- Canonical simplified ingestion commands (Epic #223):
  - `uv run atlas-data source validate --definition config/sources/<file>.yml`
  - `uv run atlas-data source run --definition ... --tier A`
  - `uv run atlas-data source dev-smoke`
  - `uv run atlas-data runs show|explain|resume --run-id <id>`
  Prefer these over source-specific `pipeline cdc-*` workflows for migrated
  sources. See `docs/operations/simplified-ingestion-migration.md`.
- Commit blank environment templates only. Do not log credentials, artifact
  contents, or unredacted request data.
- For Codex-initiated Snowflake inspection or administration, use `snow` with
  a named connection scoped to the least privilege the task needs (Epic #294 /
  Story #300 connection-surface reconciliation; see
  `docs/operations/connection-inventory.md` for the full "which connection do
  I use for X" table):
  - `ATLAS_DEV_READ` (`OH_LYME_DEV_READ`) is the **default** for routine
    DEV read/inspection work (PMC audit, migration-ledger checks, general
    reads).
  - `ATLAS_DEV_OWNER` (`OH_LYME_DEV_OWNER`) for DEV Streamlit deploy,
    governed-view/budget-procedure owner actions, and literature/paper-review
    steward decisions.
  - `ATLAS_PROD_MIGRATOR`, `ATLAS_PROD_OWNER`, and `ATLAS_PROD_RUNTIME_AUDIT`
    are the PROD equivalents; PROD actions still require explicit user scope
    and authorization for that specific action.
  - `BVB26657_PAT` (`ACCOUNTADMIN`) is **reserved, not the default** — use it
    only for an explicitly authorized administrative action that genuinely
    needs `ACCOUNTADMIN` (e.g. a cross-role `SHOW GRANTS` sweep).
  First run a bounded read-only query that reports the effective user, role,
  database, and warehouse. A missing or expired PAT is a blocker; never
  trigger an interactive browser login as a substitute. Snowflake also
  refuses to let a PAT-authenticated session mint a new PAT for that same
  user, so PAT rotation always requires the account owner to run the
  `ALTER USER ... ADD PROGRAMMATIC ACCESS TOKEN` statement interactively and
  hand you the resulting secret.
- Use a DEV, least-privilege connection by default. Production, migrations,
  roles/grants, and other privilege changes require explicit user scope and
  authorization for that specific action.
- The existing DEV PMC worker is the non-routable DigitalOcean droplet
  `oh-lyme-dev-pmc-extraction`; use its systemd service
  `oh-lyme-pmc-extraction.service` only after the protected `deploy-dev.yml`
  workflow has applied the relevant migration. Do not create a second worker,
  use production configuration, or copy secrets between environments.
- For PMC runtime verification, first inspect the approved paper and migration
  ledger through `ATLAS_DEV_READ` (renamed from `ATLAS_DEV_PMC_AUDIT` in
  Story #300; same role, `OH_LYME_DEV_READ`), then run at most the
  owner-approved
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
  Fast inner-loop ingestion tests: `uv run pytest tests/test_simplified_ingestion.py`.
- PMC retries: the three-failure ceiling applies only to confirmed LLM
  execution failures. Record provider rejections before inference in an
  append-only classification ledger; reopen an exhausted DEV paper only via
  the reviewed recovery procedure and a state event, never by editing history.
