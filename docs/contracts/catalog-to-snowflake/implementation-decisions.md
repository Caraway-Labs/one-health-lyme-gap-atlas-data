# Implementation Decisions: Catalog-to-Snowflake Pipeline Platform

## Purpose

This document is the binding technical-decision record for implementing the governed catalog-to-Snowflake pipeline described in:

- [requirements.md](requirements.md)
- [SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md](SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md)
- [source-onboarding-spec-cdc-lyme-socrata.md](source-onboarding-spec-cdc-lyme-socrata.md)
- [streamlit-snowflake-approval-app-requirements.md](streamlit-snowflake-approval-app-requirements.md)

An implementation agent must follow these decisions. It may propose alternatives only when a stated capability is unavailable in the target account or an acceptance criterion cannot be satisfied; it must explain the conflict before changing the design.

## Confirmed decisions

| Area | Decision |
|---|---|
| Pipeline runtime | Containerized Python worker, runnable locally and deployed on DigitalOcean. |
| Cloud scheduler | DigitalOcean App Platform scheduled job. |
| Discovery scope | Data.gov Catalog API v4, HealthData.gov, and Socrata/ODN only; resolve qualifying results to authoritative publisher resources. |
| Discovery cadence | Weekly. Approved sources refresh on their individually validated schedules. |
| First-release ingestion | One sequential orchestrator job; a Snowflake-backed per-resource lock prevents overlap. |
| Source onboarding | Metadata/documentation/sample first; deterministic assessment; Streamlit data-steward approval; full data only after approval. |
| Source configuration | Version-controlled JSON/YAML files, deployed with checksum/version into Snowflake `GOVERNANCE`; runtime reads approved active versions only. |
| MVP reference source | CDC/Socrata Lyme family, beginning with `x5j9-wybp`. |
| Immutable artifacts | Private DigitalOcean Spaces is authoritative; Snowflake named internal stage is temporary load transport. |
| Artifact retention | Seven-year default; no automatic deletion for active/published versions, unresolved incidents/reviews, holds, or stricter terms. |
| Snowflake authentication | Dedicated least-privilege service user with rotating key-pair authentication. |
| Snowflake loading | Worker uploads to a private named stage and uses `COPY INTO` for source-specific RAW tables. |
| Transformations | Python handles discovery/acquisition/RAW; dbt Core builds/tests `STAGING`, `CONFORMED`, and `ANALYTICS`. Do not use dbt Cloud. |
| Snowflake compute | Dedicated X-Small ingestion warehouse, auto-resume, 60-second auto-suspend, and budget/resource monitoring. |
| Environments | Separate `ONE_HEALTH_LYME_GAP_ATLAS_DEV` and `ONE_HEALTH_LYME_GAP_ATLAS_PROD` databases; development is small and fixture-driven, production performs scheduled full ingestion. |
| Review UI | Warehouse-runtime Streamlit in Snowflake approval console with owner’s rights; no external network access. |
| CI/CD | GitHub Actions and version-controlled DigitalOcean App Platform specification; protected main is the only production promotion source. |
| Python tooling | `uv`, committed `uv.lock`, Ruff, mypy, pytest. |
| Test strategy | Fixture-based unit/CI tests plus separate read-only live catalog/API smoke tests. |
| Operational visibility | Snowflake governance ledger and DigitalOcean App Platform logs only in the MVP. No external alert integration. |
| Snowflake change management | Ordered, idempotent, numbered SQL migrations run by the deployment pipeline, with applied versions/checksums recorded in Snowflake. |

## Target architecture

```text
GitHub repository + GitHub Actions
        |
        | deploy migrations, configuration, container, dbt, Streamlit
        v
DigitalOcean App Platform scheduled job
        |
        +--> discovery catalogs --> GOVERNANCE catalog/resource records
        +--> metadata/docs/sample --> assessment queue
        |                                |
        |                                v
        |                    Snowflake Streamlit approval console
        |                                |
        +--> approved source only <------+
        |
        +--> immutable artifact --> private DigitalOcean Spaces
        +--> named Snowflake stage --> COPY INTO RAW
                                      |
                                      v
                               dbt: STAGING -> CONFORMED -> ANALYTICS
```

## Repository structure

The implementation repository shall use this structure or an equivalent structure with the same responsibilities:

```text
.
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── README.md
├── app.yaml                              # DigitalOcean App Platform specification
├── catalog-search-terms.json
├── config/
│   ├── sources/                           # versioned source/access/mapping/quality config
│   └── environments/
├── migrations/
│   ├── V001__bootstrap.sql
│   ├── V002__governance_tables.sql
│   └── ...
├── src/lyme_gap_atlas_pipeline/
│   ├── cli.py
│   ├── orchestration/
│   ├── discovery/
│   ├── connectors/
│   ├── artifacts/
│   ├── governance/
│   ├── snowflake/
│   ├── quality/
│   └── settings.py
├── dbt/
│   ├── dbt_project.yml
│   ├── models/
│   ├── macros/
│   ├── tests/
│   └── packages.yml
├── streamlit_approval/
│   ├── streamlit_app.py
│   ├── snowflake.yml
│   ├── pyproject.toml
│   └── pages/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── live_smoke/
└── .github/workflows/
    ├── ci.yml
    ├── deploy_dev.yml
    └── promote_prod.yml
```

## Environment model

### Development

`ONE_HEALTH_LYME_GAP_ATLAS_DEV` is for local development, fixture-driven tests, integration tests, and previewing the Streamlit approval console. It may use small source samples and synthetic candidates. It must not create scheduled full-source ingestion or alter production objects.

### Production

`ONE_HEALTH_LYME_GAP_ATLAS_PROD` is authoritative. It contains the scheduled App Platform job, production Spaces prefix/bucket, full seven-year artifact retention, approved active source versions, and the production Streamlit approval console.

The same commit, container image, migration set, source configuration version, dbt project, and Streamlit code are promoted through environments. Never hand-edit production to bypass a repository change.

### Promotion flow

1. A pull request runs static checks, tests, dbt compilation, and container-build validation without modifying shared production resources.
2. After merge to protected `main`, GitHub Actions applies idempotent migrations and deploys the approved commit to `ONE_HEALTH_LYME_GAP_ATLAS_DEV`.
3. A protected production-environment approval promotes the same tested commit/image/configuration to `ONE_HEALTH_LYME_GAP_ATLAS_PROD`.
4. The production scheduled job runs only after production migration/configuration deployment succeeds.

## DigitalOcean deployment

### App Platform job

- Deploy one non-routable App Platform scheduled job for the production orchestrator.
- Use a container image built from the repository `Dockerfile`.
- Configure a weekly cron for catalog discovery. Source-refresh schedules must be configuration-driven and may run in the same sequential orchestrator after approval.
- The job is the only component allowed to make external catalog/publisher requests and write immutable artifacts.
- Configure runtime environment variables as encrypted secrets in App Platform. Do not expose them at build time.
- Use App Platform job activity/logs for operational diagnostics. Logs must be structured and redact secrets/protected payloads.

### DigitalOcean Spaces

- Use private Spaces storage; no public bucket, public object ACL, or CDN exposure.
- Enable versioning and maintain a documented recovery/backup approach; Spaces is not a substitute for backups.
- Use separate environment prefixes or buckets, such as `topx-pipeline-dev/` and `topx-pipeline-prod/`.
- Store source payloads, catalog responses, documentation snapshots, schema snapshots, and manifests under deterministic keys that include environment, source resource key, ingestion run ID, and artifact checksum.
- Write an artifact successfully to Spaces and verify the checksum before attempting Snowflake load.
- Lifecycle deletion is a controlled cleanup process, not a native blind expiration rule: it must consult active/published source-version, review, incident, and hold status before deletion.

## Snowflake platform model

### Databases and schemas

Create the same schema family in each environment database:

```text
ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE       ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE
ONE_HEALTH_LYME_GAP_ATLAS_DEV.RAW              ONE_HEALTH_LYME_GAP_ATLAS_PROD.RAW
ONE_HEALTH_LYME_GAP_ATLAS_DEV.STAGING          ONE_HEALTH_LYME_GAP_ATLAS_PROD.STAGING
ONE_HEALTH_LYME_GAP_ATLAS_DEV.CONFORMED        ONE_HEALTH_LYME_GAP_ATLAS_PROD.CONFORMED
ONE_HEALTH_LYME_GAP_ATLAS_DEV.ANALYTICS        ONE_HEALTH_LYME_GAP_ATLAS_PROD.ANALYTICS
ONE_HEALTH_LYME_GAP_ATLAS_DEV.FEATURE_STORE    ONE_HEALTH_LYME_GAP_ATLAS_PROD.FEATURE_STORE
```

Implement the 15 governance entities and dataset-specific RAW standard columns defined in `SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md`. Standard Snowflake PK/FK declarations are documentation only; pipeline code/tests must validate relationships.

### Warehouses and roles

- Create `OH_LYME_INGEST_XS_WH` or the environment-prefixed equivalent as the dedicated ingestion/dbt warehouse, auto-resume enabled and auto-suspend set to 60 seconds.
- Create a separate X-Small approval-console warehouse, `ONE_HEALTH_LYME_GAP_ATLAS_<ENV>_APPROVAL_XS_WH`, with the same suspend policy.
- Set resource monitors/budget alerts appropriate to the Snowflake account. Attribute jobs through query tags that include environment, component, run ID, and source resource key.
- Use separate least-privilege roles for pipeline runtime, Streamlit owner, data steward, read-only approval viewer, and security administration as defined in the Streamlit requirements.

### Service-user authentication

- Create a dedicated non-human Snowflake service user for the DigitalOcean worker.
- Use encrypted key-pair authentication; register and rotate public keys in Snowflake according to a documented runbook.
- Locally, `.env` may reference an encrypted private-key file path and passphrase.
- In App Platform, inject a base64-encoded encrypted private key and its passphrase as separate encrypted runtime secrets; decode/use the key in memory only.
- The application must never write the private key, decoded bytes, passphrase, access token, or connection configuration into artifacts, logs, table columns, or error output.

### Artifact-to-RAW loading

1. Save immutable source bytes in DigitalOcean Spaces and calculate SHA-256.
2. Create the corresponding `GOVERNANCE.RAW_ARTIFACTS` record and load manifest.
3. Use a private named Snowflake internal stage as temporary transport.
4. Upload the verified artifact to the stage.
5. Execute `COPY INTO` for the dataset-specific RAW table.
6. Record query ID, raw load batch ID, row counts, stage/load result, source artifact ID, and ingestion run ID.
7. Retain source-faithful `VARIANT` payloads and required provenance fields; do not perform business transformations in RAW.

Do not use per-row inserts for production acquisition. Do not introduce Snowpipe or a direct Snowflake external stage against Spaces during the MVP.

## Pipeline design

### Discovery and onboarding

- Load [`catalog-search-terms.json`](catalog-search-terms.json) as a validated runtime input.
- Search Data.gov Catalog API v4 with `DATA_GOV_API_KEY`; do not use `DEMO_KEY` in scheduled environments.
- Search HealthData.gov and Socrata/ODN through the configured Socrata Discovery API patterns, using `SOCRATA_APP_TOKEN` where configured/required.
- Run all enabled term groups weekly; retain full results, request records, and raw response artifacts.
- Classify every result/resource, resolve canonical publisher resource where feasible, and identify mirrors.
- Retrieve only metadata, documentation, and a sample before review. Full payload acquisition is prohibited at this point.
- Execute deterministic source assessment and write the results/evidence to `GOVERNANCE.DATASET_QUALITY_ASSESSMENTS`.
- Route eligible candidates to `SOURCE_APPROVAL_CONSOLE`. Full ingestion is allowed only when a data steward’s controlled approval activates the source version/access profile.

### Sequential orchestration and locking

- A single orchestrator command coordinates discovery, assessment, approved-source ingestion, and dbt invocation.
- Before handling a resource, acquire a Snowflake-backed per-resource lock with lease/expiry, owner run ID, and safe cleanup rules.
- Do not begin a second run for a locked resource. Record the skip/blocked status and reason.
- Design each source connector as a stateless adapter with explicit input configuration and output manifests so later parallel workers can be added without governance-schema redesign.

### CDC/Socrata reference pipeline

- Implement `x5j9-wybp` first as the full end-to-end reference source.
- Capture source metadata, documentation, schema/sample, requests/pages, immutable artifacts, checksums, row counts, and failed/partial evidence.
- Require deterministic order before any offset pagination.
- Preserve the 2022-current surveillance era separately from `qtbi-xd4i` (2008–2021) and `84rx-ksgd` (1992–2007).
- Do not allow line-listed CDC data without geography to join county contextual facts.

## Transformations and data quality

### dbt Core

- Install dbt Core and the Snowflake adapter in the same container/toolchain; do not purchase or depend on dbt Cloud.
- Use dbt for SQL models, documentation, and tests from `RAW` through `STAGING`, `CONFORMED`, and `ANALYTICS`.
- Python retains responsibility for external I/O, artifact/manifests, provenance writes, and RAW loads.
- Invoke dbt only with approved input source versions. Persist dbt run/result artifacts, target relation, code version, query IDs, and quality results in the transformation ledger.

### Quality controls

- Configure source-specific mappings and quality rules in repository files; deploy their version/checksum to `GOVERNANCE`.
- Treat schema/documentation/license/case-definition/geography/time-semantic changes as review-gated events.
- Preserve distinct numeric-zero, null, unknown, suppressed, and not-reported states throughout all layers.
- Do not treat plausible public-health patterns as ETL failures without source-specific evidence.

## Streamlit approval console

Implement the application exactly as specified in [streamlit-snowflake-approval-app-requirements.md](streamlit-snowflake-approval-app-requirements.md):

- Warehouse-runtime Streamlit in Snowflake with owner’s rights.
- Dedicated owner role and approval warehouse.
- No external access integration, external API request, or app secret.
- Viewer identity captured through `st.user.user_name`, never owner-rights `CURRENT_USER()`.
- Evidence displayed through governed/redacted views.
- Decisions written only through a controlled stored procedure; decisions are immutable and superseded, never edited/deleted.
- UI failure must leave candidates pending and must never permit a worker to bypass approval.

## Configuration and secrets

Commit `.env.example` with blank values only. Ignore `.env`, private-key files, credential exports, and generated local artifact directories.

```dotenv
# Catalog discovery
DATA_GOV_API_KEY=
SOCRATA_APP_TOKEN=

# Snowflake local development
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_ROLE=
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=
SNOWFLAKE_PRIVATE_KEY_PATH=
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=

# Snowflake App Platform production runtime
SNOWFLAKE_PRIVATE_KEY_B64=

# DigitalOcean Spaces
SPACES_REGION=
SPACES_ENDPOINT=
SPACES_BUCKET=
SPACES_ACCESS_KEY_ID=
SPACES_SECRET_ACCESS_KEY=
```

Production values must be encrypted App Platform runtime secrets. API keys belong in `.env` only for local development and in encrypted runtime secrets for deployment. Never echo, log, commit, or place their values in Snowflake evidence records.

## Migrations and deployment

### SQL migrations

- Use ordered filenames: `VNNN__short_description.sql`.
- Every migration must be safe to rerun or explicitly fail before partial mutation; destructive changes require a forward-only replacement/migration rather than dropping governed history.
- The Python migration runner creates and consults a schema-migration ledger containing version, filename, SHA-256, applied timestamp, deployment commit, and executor identity.
- Apply the same migration set to `ONE_HEALTH_LYME_GAP_ATLAS_DEV` before production promotion. A checksum mismatch must halt deployment.

### GitHub Actions

Pull-request CI must run at minimum:

```text
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
dbt deps
dbt parse
container build
```

Additional protected environment workflows must:

1. Apply/verify SQL migrations.
2. Deploy source configuration and validate its checksum.
3. Deploy or update the Streamlit app using Snowflake CLI/declarative configuration.
4. Build/deploy the App Platform scheduled-job specification.
5. Verify the job has encrypted runtime secrets configured without reading their values.
6. Run a bounded post-deploy smoke check; do not trigger a full catalog crawl as a deployment test.

## Testing and operational checks

### Normal CI

- Use redacted/version-controlled fixtures for discovery responses, source metadata, schemas, documentation summaries, data pages, failed requests, and review decisions.
- Test pagination, canonical-source/mirror resolution, configuration validation, artifact hashing, Spaces upload abstraction, stage/COPY manifest creation, locks, quality gates, and secret redaction.
- Test dbt models and source-specific semantic constraints in `ONE_HEALTH_LYME_GAP_ATLAS_DEV` using fixtures/synthetic data.
- Test Streamlit authorization and approval procedure behavior by role.

### Live smoke checks

- Run separately from pull-request CI and full scheduled production ingestion.
- Use read-only bounded requests to Data.gov v4, HealthData.gov, Socrata/ODN, and the CDC/Socrata reference source.
- Assert reachable endpoint, expected authentication behavior, parsable response, and essential metadata/schema fields.
- Store redacted request evidence and alert only through logs/governance status in the MVP.

### Operational review

- Operators inspect App Platform job activity/logs and Snowflake governance status for failed, partial, stale, blocked-review, or skipped-lock runs.
- Snowflake query tags and ledger references must correlate the external run, artifact, `COPY INTO`, dbt execution, and downstream asset.
- Review warehouse/resource-monitor usage and Spaces retention/storage periodically; scale only from observed workload.

## Explicit non-goals

- No dbt Cloud, Airflow, Kubernetes, Snowpipe, external alerting system, external approval web app, or direct Spaces-to-Snowflake external stage in the MVP.
- No automatic full ingestion of discovered candidates.
- No pipeline-driven acquisition of controlled, restricted, clinical, or participant-level data.
- No manual production schema/table edits outside version-controlled migrations.
