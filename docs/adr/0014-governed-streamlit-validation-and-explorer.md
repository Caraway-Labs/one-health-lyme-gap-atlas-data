# 0014: Governed Streamlit Validation and Data Explorer

Status: Accepted
Date: 2026-09-07
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

The source-approval console safely showed approval and pipeline state but did
not provide enough post-ingestion evidence for a steward to assess a completed
DEV run. Direct access to `RAW`, `STAGING`, and `CONFORMED` would expose
payloads or unnecessarily broaden the approval application's privileges.

## Decision

Add a read-only post-ingestion validation page to `SOURCE_APPROVAL_CONSOLE`.
It reads `GOVERNANCE.V_SOURCE_INGESTION_VALIDATION`, which contains only run
status, stable IDs, counts, timestamps, quality-result counts, and the source
caveat.

Create the separate `GOVERNED_DATA_EXPLORER` Streamlit application. It queries
only allow-listed `GOVERNANCE.V_DATA_EXPLORER_*` views that project curated
CDC/Socrata fields from `CONFORMED` and an explicitly non-aggregated,
analytics-ready projection. Neither application can query `RAW`, show payloads or
artifact locations, call external services, or write data. Both remain owned
by the existing constrained Streamlit owner role and available only to the
existing internal steward/viewer roles.

V041 is executed by `OH_LYME_<ENV>_GOVERNED_VIEW_OWNER`, a separate
deployment-only role. It owns the four views and has `SELECT` only on their
named dependencies: the CDC RAW and CONFORMED relations, the three governance
ledgers used for validation, and `SCHEMA_MIGRATIONS` for the checksum runner.
The migration service identity may assume this role for V041 only; it is not
granted to the Streamlit owner, steward, viewer, or pipeline runtime roles.

## Consequences

Stewards can inspect whether a source version reached a materialized CONFORMED
relation and browse bounded, paginated curated records with provenance and
surveillance-era caveats. This does not create a public API, change the Alpha
POC, add a disease-risk measure, or authorize cross-era comparisons.

The standard migration role does not receive RAW or CONFORMED access. A later
migration therefore cannot acquire source-data visibility merely because it
runs through the default deployment path.

## Rollout, observability, and rollback

Deploy migrations and both apps to DEV first, validate the governed views and
app pages, then promote the identical reviewed source through the protected
PROD workflow. Rollback redeploys the prior approved app source; retained
ingestion and provenance records are never deleted.
