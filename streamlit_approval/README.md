# SOURCE_APPROVAL_CONSOLE

This Snowflake-native application reads only governed views and records a
decision only through `GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION`. It makes
no external network requests and has no secrets or App Platform credentials.

## Pipeline observability

The console includes a read-only operational dashboard in addition to the
steward-review workflow. Its pages are Overview, Pipeline command center,
Pipeline health, Registration recovery, Artifact backlog, Discovery coverage,
Search coverage and gaps, Registration outcomes, Governance & approval, and
Run explorer. The command center is scoped to the latest completed discovery
chain and never presents historical retained inventory as current work.

The Overview explains the three intentionally different counts:

- **Historical inventory**: every immutable successful catalog response kept
  for provenance across all discovery attempts.
- **Active registration chain**: artifacts in the latest completed discovery
  chain eligible for metadata registration.
- **Durably processed**: active-chain artifacts whose registration checkpoint
  committed successfully.

Expired leases and failed registrations remain visible as unresolved work; the
app does not retry, reclaim, approve, acquire, or transform data. Every
operational query uses a redacted `GOVERNANCE.V_PIPELINE_*` view and excludes
artifact payloads, request bodies, artifact locations, and credentials.

Registration recovery is based on durable invocation summaries. A `PARTIAL`
result means the bounded metadata-registration invocation reached a declared
artifact or dataset limit; it is not a failed full-source ingestion. Search
coverage makes recorded zero-result requests explicit, but never calls an
absent request "unattempted" because that would require a separately deployed
search-plan ledger.

## Controlled deployment and verification

Apply `migrations/V033__pipeline_observability_views.sql` and
`migrations/V039__pipeline_operations_console.sql` to DEV before PROD,
using the governed migration runner so its checksum is recorded. Deploy this
directory with the dedicated `<ENV>_STREAMLIT_OWNER` role, then verify each
`V_PIPELINE_*` view as that owner role before granting viewer access. The
artifact backlog is server-side paginated; verify it with both a normal status
filter and the expired-lease-only filter. Promote the same reviewed source to
PROD only after the DEV application and view checks succeed.
