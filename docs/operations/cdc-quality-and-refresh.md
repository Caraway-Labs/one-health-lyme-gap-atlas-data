# CDC quality evidence and approved routine operation

## Implemented quality evidence

Every successful CDC dbt build now validates retained rows and appends eight
aggregate checks per original ingestion run to GOVERNANCE.DATA_QUALITY_RESULTS.
The standalone `pipeline validate-cdc-quality --source-version-id <id>` performs
the same validation without fetching source data or rebuilding models.

Checks cover nonempty RAW, RAW-to-CONFORMED counts, payload/artifact/run multiset
equality, required provenance, registered artifact/run lineage, content-hash
integrity, duplicate content hashes within a run, and source-value preservation.
Results share a validation ID and timestamp; failures are committed before the
command fails. No source payload or failing record is persisted in diagnostics.
The validation page counts all retained results, including historical failures;
these counts are evidence history, not a latest-batch-only quality score.

The captured source does not contain Socrata system IDs. Content hashes provide
integrity and exact-duplicate detection, not stable publisher record identity.
The apparent county/year/case/sex/age tuple is not unique and is not enforced as
a key. Numeric zero, null and explicit unknown/suppressed/not-reported strings
must remain distinguishable. Payload equality verifies unchanged original
states; null-safe projection comparisons and status checks verify curated data.

In the operating-policy release, dbt builds a candidate relation, not the public
CONFORMED relation. Passing checks authorize copying an immutable snapshot and
atomically switching its publication pointer. A failed candidate remains invisible.

## Approved operating policy (ADR 0018)

Observed on 2026-09-08 UTC: the PROD approved-source job is scheduled at 09:00
America/Denver every January 15. No job or app alerts are configured in its app
specification. The profile describes annual source updates. The loader appends
each refresh as a new RAW run and CONFORMED includes all active approved runs.
An ingestion exception rolls back its run record with its transaction, so the
durable failure evidence available for dbt recovery is not yet equivalent for
full acquisition failures.

1. Use a monthly metadata/change check, followed by an explicitly authorized full
   refresh when publisher content changes. Do not tie discovery of an annual
   release to an assumed January publication date.
2. Keep immutable RAW snapshots. Serve only the latest successfully validated
   snapshot per source version, with an atomic publication pointer. Skip unchanged
   snapshots by checksum; rerunning the same snapshot must not multiply output.
   Do not merge records by the currently unverified natural key.
3. Keep the prior validated snapshot visible on a failed refresh. Record every
   acquisition attempt and terminal failure outside the rolled-back load
   transaction. Alert once on terminal failure or overdue successful checks;
   use bounded retries for transient network errors and no automatic retry loop
   for approval, schema, permissions, or quality failures.
4. Before unattended operation, demonstrate an unchanged-source rerun, a changed
   snapshot, a forced failure, and restoration of the prior published snapshot
   in DEV. Add a source-identity investigation for missing publisher IDs.

The owner approved these recommendations in the ingestion task. Deployment is
not proven by this document: record the release digest, migration checksum,
bootstrap run, DEV scenario results, protected PROD workflow, and live pointer
verification before marking the rollout complete.

## Controlled rollout and commands

1. Apply forward-only migration V043 in DEV. Do not rebuild dbt first: the old
   public view is the bootstrap input. Deploy the tested operating-policy image.
2. Run `pipeline bootstrap-cdc-publication --source-version-id <id>
   --ingestion-run-id <existing-raw-run>` under the environment runtime role.
   It validates the existing public rows, copies them, creates the pointer, and
   replaces the public view with snapshot serving. Confirm the original 5,045
   records and provenance are still visible in Streamlit.
3. Run `pipeline check-cdc-metadata`. Retain its `check_id` and change status.
   This command does not download source rows. A fingerprint is an update signal,
   not proof of byte-identical publisher data.
4. An operator may authorize `pipeline promote-approved-cdc --check-id <id>`.
   PROD uses the protected manual workflow with this ID. Approval and metadata
   are checked again before acquisition; metadata is checked after acquisition.
   A source-version change or unstable publisher snapshot fails closed.
5. The promotion result distinguishes `PUBLISHED` from `UNCHANGED`. An unchanged
   content checksum leaves the visible pointer and row count unchanged; RAW
   attempts and source artifacts remain retained for audit.
6. To restore retained data, run `pipeline rollback-cdc-publication
   --source-version-id <id> --ingestion-run-id <retained-run>
   --expected-revision <current-revision>`. It requires original passing quality
   evidence, a complete retained snapshot, active approval, and the current
   revision. It appends a rollback event without deleting evidence. A concurrent
   publication requires a fresh operator decision, not a blind retry.
7. Prove unchanged/change/failure/rollback scenarios in isolated DEV fixtures and
   the real unchanged snapshot path before promoting the exact digest to PROD.
   Repeat bootstrap in PROD using its own approved source version and RAW run.
8. Enable monthly checks at 09:00 America/Denver on day 1 only after bootstrap
   and notification delivery are verified. Run `pipeline check-cdc-overdue` daily;
   a missed successful check after seven days generates one monthly incident key.

### Failure handling and rollback boundaries

Full-acquisition failures retain a FAILED run even when row loading rolls back.
Validation failures retain quality evidence and the last good publication.
Runtime crashes may leave RUNNING attempts; provider failure/overdue monitoring
must catch these rather than treating missing terminal records as success.
Source HTTP/network retries are bounded; approval, schema, permissions and
validation failures require an operator. Alerts contain identifiers and controlled
classifications only, never payloads, private artifact locations or credentials.

Data rollback uses retained snapshots. Do not deploy the pre-policy dbt digest
as an unattended job after bootstrap: that version can replace the public view
with historical RAW serving. Disable CDC execution before any code rollback and
restore the pointer-backed public view before resuming. Forward migrations and
retained evidence are not reverted.

### Notification activation

The daily `Monitor CDC routine operation` workflow uses only DigitalOcean job
invocation metadata and protected-refresh workflow status. Its repository-scoped
GitHub token can create issues; it cannot deploy or query Snowflake. Configure
`DIGITALOCEAN_MONITOR_READ_TOKEN` as a separate read-only repository secret, never
copy the protected deployment credential into this monitor. Set
`CDC_MONITOR_ENABLED_AT` to the verified successful initial metadata baseline's
UTC timestamp, then set `CDC_MONITOR_ENABLED=true` after a delivery test.

Each incident has a stable marker in its GitHub issue. The monitor checks all
existing receipts, including closed issues, before creating another. An uncertain
delivery is reconciled on the next run; receipt-lookup failures stop delivery
rather than blindly creating duplicate issues. Overdue incidents are keyed by
month. Snowflake retains the controlled failure ledger; GitHub retains the
notification receipt. No source payload or private artifact location is sent.
