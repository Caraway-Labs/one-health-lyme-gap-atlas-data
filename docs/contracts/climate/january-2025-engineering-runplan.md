# Bounded January engineering continuation

Matthew's accepted January inputs and four definitions are recorded in the
product decision; no repeat owner acceptance is required. This plan is not a
publication receipt and supplies no fabricated source IDs or review times.

1. Independently review the protected reconciliation workflow and exact main
   commit, then run `run-ingestion.yml` with `operation=january-source-registration`,
   `registration_phase=inspect`, the exact January definition/run, DEV/Tier B and
   `recapture=false`, `publish=false` and
   `reviewed_commit` equal to that reviewed full SHA. The existing DEV pipeline
   runtime must authenticate exactly; no new credential or grant is configured.
2. Run the same reviewed workflow with `registration_phase=register-pending`. Existing matching
   identities are reused; both URLs, linked dataset keys, retained checksums and
   completed selected run are checked before any INSERT. Both inputs register in
   one transaction; inactive resources and PENDING versions confer no approval.
   Concurrency serializes these workflow calls. Inspect the bounded post-action
   readback and retain actual source-version IDs; do not infer success from a
   dispatch receipt or use a different key to bypass a conflict.
3. Persist the already supplied source/metadata acceptance through the reviewed
   owner-only decision phase and existing active steward authority. Preserve
   truthful recording/original-time provenance; a missing original timestamp is
   not permission to invent one. The runtime cannot execute this phase. V075
   remains unchanged. Re-read the actual appended decision/version joins before
   using them in final metadata; no new owner product decision is requested.
4. Assemble final reviewed CONSUMER_SAFE metadata with actual live source IDs,
   legitimate review time/evidence, recomputed revisions, frozen selected capture
   membership and its digest. The verified candidate is 389856 rows with repeated
   SHA256 `1e6b9809a5266d7cb3b4851f861835fdfddcf0d4f136a02d14e7e436806f5618`.
   Do not publish the pending review packet or substitute fixture IDs.
5. Prove the protected publication identity can read the canonical normalized
   partitions and revisions and reconstruct the complete target candidate.
   Use existing `publish-semantic-release.yml` with exact reviewed main commit
   and reviewed manifest for build, then publish only after persisted extension
   validation and rollback readiness. Review the current ATLAS release and annual
   source slots first; climate must not discard concurrent annual release work.
6. Verify the actual API reader in its existing authorized service environment,
   with bounded identity and two-view read proof. Limited owner/migrator visibility
   and configuration files cannot substitute. Prepare an actionable minimal
   view-only grant request only after the principal and target context are proven;
   obtain specific authorization before persistent grants. Activate the flag only
   after matching release metadata and observations pass consumer acceptance.

DEV view V136 already exists under its verified protected service; PROD requires
separate target visibility, migration/source/capture parity and publication
evidence. No DEV-only migration or capture is silently promoted. The denied
secret-bearing app-spec/unrestricted console paths are not used for diagnosis.
History remains deferred; DATA #443/#431 retain their existing follow-on scope.
