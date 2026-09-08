# CDC quality evidence and proposed routine operation

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

These checks run after dbt: failure reports bad data but does not atomically
roll back publication. Atomic promotion is a separate proposed operating change.

## Recommendations awaiting owner decision

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

These operating-policy recommendations are not implemented by this increment.
