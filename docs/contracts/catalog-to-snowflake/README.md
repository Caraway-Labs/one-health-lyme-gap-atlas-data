# Codex Implementation Handoff

This folder is the self-contained specification package for building the TOPx governed catalog-to-Snowflake data-pipeline platform.

## Required reading order

1. [implementation-decisions.md](implementation-decisions.md) — binding technical choices; do not re-litigate them.
2. [requirements.md](requirements.md) — functional, non-functional, and test requirements.
3. [source-onboarding-spec-cdc-lyme-socrata.md](source-onboarding-spec-cdc-lyme-socrata.md) — discovery/onboarding behavior and first CDC/Socrata reference pipeline.
4. [catalog-search-terms.json](catalog-search-terms.json) — runtime discovery input; preserve its schema and enabled/disabled term-group behavior.
5. [SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md](SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md) — authoritative governance schema and provenance contract.
6. [streamlit-snowflake-approval-app-requirements.md](streamlit-snowflake-approval-app-requirements.md) — Snowflake-hosted approval-console requirements.
7. [catalog-to-snowflake-ingestion-diagrams.md](catalog-to-snowflake-ingestion-diagrams.md) — architecture diagrams and shared mental model.
8. [.env.example](.env.example) — local-development environment-variable template; copy it to `.env` and keep values out of Git.

## Codex instructions

- First produce an implementation plan that maps every requirement ID and acceptance criterion to a repository artifact, migration, configuration, test, or deployment step.
- Do not implement until the plan is approved by the user.
- Follow `implementation-decisions.md` as binding. Raise a blocker only when a target-account/platform capability prevents compliance.
- Start with the CDC/Socrata `x5j9-wybp` reference pipeline; do not add uncontrolled additional sources.
- Preserve immutable evidence, source semantics, human approval gates, least privilege, secret redaction, and forward-only migration history.
- Do not place real credentials, API keys, private keys, or `.env` contents in the repository, tests, output, or documentation.
- Use local fixtures for normal tests and bounded read-only live smoke tests separately.

## Package completeness

The files in this folder are sufficient to plan and implement the MVP described here. They intentionally exclude broad research material and raw data extracts because those would expand scope or become stale. The implementation must verify live source endpoints, schema, terms, and platform configuration before enabling a source in production.

## Expected first deliverables

- Repository scaffold, Python container, `uv` toolchain, CI workflows, and DigitalOcean App Platform specification.
- Numbered Snowflake migrations for environments, roles, governance entities, views/procedures, warehouses, and stages.
- Validated catalog configuration deployment and three discovery adapters.
- CDC/Socrata `x5j9-wybp` onboarding, artifact-to-RAW path, quality controls, and dbt promotion path.
- Streamlit in Snowflake `SOURCE_APPROVAL_CONSOLE` and controlled decision procedure.
- Fixture, integration, live-smoke, and access-control test suites.
