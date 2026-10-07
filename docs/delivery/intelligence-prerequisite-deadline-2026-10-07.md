# Exact intelligence prerequisite deadline

The reviewed minimum DEV feed SQL currently has no owned process deadline when
passed to the existing reviewed migration command. For exactly its pinned SHA256
running alone, start the existing watchdog before settings/connection setup and
keep it active across pending-plan checks, legacy reconciliation, application,
commit/cleanup and result output. Exit124 at50seconds performs no evidence I/O.
Mixed batches containing that exact SQL are rejected before connection setup.
Existing generic migration behavior and the feed's default300seconds stay intact.

Reuse ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS to apply ten-second statements through
the existing sql_sessions.connect surface, which also sets queuedtimeout10 and
ABORT_DETACHED_QUERY. Preserve stronger existing statement limits and restore the
prior environment on normal/error return. No new migration number, credential,
role, grant or execution route is created. The canonical6809-byte SQL is unchanged.

The owned50seconds is not a guarantee that the last server statement stops at the
same instant. Reserve its bounded server tail separately. DDL auto-commits, so a
timeout can leave partial objects without a completed migration receipt. Reverify
actual ownership/schema/privileges and reconcile the pending set before any retry;
never assume rollback or repair through wider privileges.

The public metadata-confirmation description now covers the separate forward-only
US$8 allowance; it does not attest historical charges. No private amounts, prices
or evidence references are placed in workflow inputs/env/logs. No dispatch or live
SQL is performed by this change. Actual warehouse cost properties and independent
review remain prerequisites for execution.

The existing2500-query ceiling covers the whole bounded feed path, including up
to250 normalized items and their provenance/checkpoint/write transactions. It is
not a target or a requirement for acquisition-only. The shared runtime has no
phase-specific smaller ceiling today; this deadline patch intentionally does not
change ingestion behavior. The existing fail_after_stage=ACQUIRE stop can bound
stage scope after genuine source/retention authority is established; a smaller
query cap would need a separately verified phase budget rather than an invented
SQL count. Process/request limits provide the primary owned-work bound.
