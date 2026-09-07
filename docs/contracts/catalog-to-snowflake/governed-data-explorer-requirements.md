# Requirements: Governed Data Explorer

## Purpose and scope

`GOVERNED_DATA_EXPLORER` is an internal, read-only Snowflake Streamlit app for
curated CDC/Socrata `x5j9-wybp` records that have reached `CONFORMED` and the
explicit `ANALYTICS` projection. It complements `SOURCE_APPROVAL_CONSOLE`; it
does not approve sources, start pipelines, or replace the Python public API.

## Access and data contract

- The app runs with the existing `OH_LYME_<ENV>_STREAMLIT_OWNER` owner-rights
  role on the approval X-Small warehouse.
- `DATA_STEWARD` and `APPROVAL_VIEWER` may use the app. Neither receives direct
  table, stage, write, or ownership privileges.
- The app reads only `GOVERNANCE.V_DATA_EXPLORER_SOURCE_VERSIONS`,
  `GOVERNANCE.V_DATA_EXPLORER_CONFORMED_CDC`, and
  `GOVERNANCE.V_DATA_EXPLORER_ANALYTICS_CDC`.
- Rows retain source version, ingestion run, artifact identifier, retrieval
  timestamp, source grain, geography/time semantics, and the CDC reporting-era
  caveat. RAW payloads, artifact locations, request details, credentials, and
  external network calls are prohibited.

## User experience and acceptance criteria

- A user can choose a source version, inspect its safe run summary, and page
  through CONFORMED or ANALYTICS records with a bounded optional report-year
  filter.
- Queries use parameter binding and fixed view allow-lists. Results are capped
  at 250 rows per page.
- The app says when no source version or no matching rows exist; it must not
  infer that an absent row means a source was never attempted.
- It prominently presents the surveillance-era caveat and makes no diagnosis,
  risk, cross-era-trend, or causal claim.

## Rollout and rollback

Apply the view/grant migration and deploy both Streamlit apps to DEV first.
Validate with the owner role, then promote the same reviewed source to PROD.
Rollback redeploys the prior app source and leaves provenance records intact.
