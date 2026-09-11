# 0018: CDC snapshot publication and routine operation

Status: Accepted
Date: 2026-09-08
Decision owner: Atlas owner, approved in the ingestion task

## Context

The owner approved monthly metadata checks, operator-authorized changed-source
refreshes, immutable RAW snapshots, checksum deduplication, durable failure
reporting, and retaining the previous validated publication after failures.
The existing CONFORMED view includes every active approved RAW run. Replacing
that view before validation can expose a failed candidate or duplicate history.

## Decision

Keep source approval unchanged. Acquire only after an explicit operator command;
the monthly command captures metadata and records a change signal only. Compare
publisher update markers and schema before and after acquisition to reject an
unstable capture. A metadata fingerprint is a change signal, not a content hash.

Build a separate CDC candidate relation. Persist eight quality checks against
one candidate ingestion run before publication. Copy passing candidate rows into
an immutable snapshot table and atomically update a per-source-version pointer.
The public CONFORMED relation reads only those retained rows selected by the
pointer. Neither a dbt rebuild nor a failed load changes the visible snapshot.

Use a sorted multiset of canonical source-row hashes for a versioned content
checksum independent of page order. Do not treat an unverified demographic tuple
as a publisher key. Unchanged content does not advance the publication pointer.
Retain acquisition artifacts and attempts, including an unchanged result.

Serialize CDC operations with a bounded resource lease. Publication uses an
expected revision check so a stale worker cannot replace a newer publication.
Rollback selects an existing validated snapshot and appends an audit event; it
does not remove RAW, artifacts, quality results, or snapshot history.

Commit the attempt record before the load transaction. On exception, roll back
the load, then record a controlled terminal failure separately. Retry only
transient HTTP/network failures, at most three attempts with bounded backoff.
Approval, schema, permission, and quality failures require operator action.

Record redacted incidents using stable incident keys. A daily watchdog detects
monthly metadata checks overdue by more than seven days. Deliver one notification
per incident through the owner-selected channel, retaining delivery receipts.
Do not put source payloads, credentials, or private artifact locations in alerts.

## Acceptance and deployment

Prove unchanged-content reruns, changed snapshots, rejected candidates, concurrent
publication rejection, rollback, and durable failure reporting in DEV. Verify
Streamlit reads through the existing restricted governance views. Promote the
DEV-tested digest through the protected production workflow. The monthly check
replaces the annual full-data schedule only with the complete operating path.

## Contracts

Extends the catalog-to-Snowflake contract and ADRs 0005/0006, 0014, and 0017.
No public API, frontend, source approval, surveillance-era, or privacy changes.
