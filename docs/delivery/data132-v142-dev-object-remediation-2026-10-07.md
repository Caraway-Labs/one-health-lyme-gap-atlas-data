# DATA #132/#135 DEV object remediation

Matthew's interactive `ACCOUNTADMIN` information-schema check on 2026-10-07
returned no table, column, or view rows for the two raw-retention tables and
`PRESENTATION.INTELLIGENCE_FEED_V2`. This is owner-level absence evidence, not an
inference from an agent role's visibility. The read-only `ATLAS_DEV_READ`
session verified `OH_LYME_DEV_READ`, the suffixed DEV database, and the DEV ingest
warehouse. The DEV ledger contains V135 at the reported checksum and timestamp;
it also contains V136, V137, V138, and V140, but no later intelligence migration.
All 115 ledger filenames map to repository files. A source hash comparison
matches except historical V033, whose legacy checksum is explicitly handled by
the existing migration runner. No ledger row was changed.

V135 created the source registry, guard, revisions, captures, contexts, and
legacy V1 view. It never included the raw-retention documents/audit tables or
V2 view. Those three objects appear in unnumbered review SQL only:
`raw-runtime-schema-review.sql`, `presentation-projection.sql`, and the
consolidated DEV minimum-access review SQL. No later numbered migration creates
them. The cause is an unpromoted review template, not an unapplied V135 or
evidence of a later drop. V1 exists but its observed definition lacks the
reviewed v1 contract-version filter.

V142 is the DEV-only forward repair. It creates the two absent tables using
the reviewed columns, corrects V1 with `COPY GRANTS`, creates V2 using the
reviewed v2 projection, and grants only runtime SELECT/INSERT on documents,
runtime INSERT on audit, and DEV reader SELECT on V2. The migration owns the
three new objects under the existing DEV migration deployer. It does not add
source rows, acquisition, DELETE, cleanup approval, purge procedure, API
reader rights, or PROD objects. These remain separately governed.

The protected prerequisite selector pins V142's version, filename, and source
SHA256 and verifies them against `load_migrations()`. Both `deploy-dev.yml` and
the reviewed DEV CLI use that selector. The CLI requires explicit accounting
confirmation, starts the 50-second process and 10-second statement bounds
before settings/connection work, checks the exact migration-service identity,
and rejects mixed or mismatched pending sets before reconciliation/application.
The generic migration runner rejects a pending V142 before executing any DDL;
only the protected reviewed route can pass its second execution guard. The
historical unnumbered review-template checksum is no longer a dispatch key.

`CREATE TABLE/VIEW IF NOT EXISTS`, `CREATE OR REPLACE VIEW ... COPY GRANTS`, and
repeated exact grants make the SQL safe to rerun after a partial Snowflake DDL
failure. `IF NOT EXISTS` does not validate an unexpected preexisting object:
repeat the exact owner metadata check before dispatch and verify owner, columns,
definitions, and grants afterward. The protected deploy workflow must receive
the exact reviewed pending version/filename/checksum set for the dispatch SHA;
it must never rewrite V135 or the ledger. A partial failure requires an
object-by-object review before retry. Recovery retains created objects and
provenance; disable runtime dispatch if needed, then use a new forward migration
for any incompatible live shape.

The raw 30-day deletion authority remains incomplete: the separate reviewed
cleanup approvals and owner-rights purge procedure are not in V142. EID
registration/acquisition stays blocked until that control and the genuine
source-specific restricted-artifact/native-policy receipts are reviewed and
the protected prerequisite diagnostic passes for EID and required objects.
NIH can remain independently blocked. PR #637 should be updated to reference
V142 and its post-deploy evidence; PR #631 remains a nonexecutable admission
candidate pending those reviews.
