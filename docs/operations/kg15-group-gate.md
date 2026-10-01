# KG15 extraction group gate: first implementation slice

This is an offline-reviewed inventory/claim seam, not authorization to run a
production canary. The existing protected one-shot workflow does not yet expose
this manifest. Do not introduce an unreviewed deployment input or use legacy
one-paper invocations as proof that KG15 group acceptance is complete.

An explicitly supplied `ATLAS_EXTRACTION_GROUP_MANIFEST` selects the group path.
Absence preserves the existing one-paper path; an empty or malformed value blocks.
The manifest accepts exactly these fields:

```json
{
  "group_id": "22345678-1234-4234-8234-123456789abc",
  "discovery_run_id": "12345678-1234-4234-8234-123456789abc",
  "pmids": ["1000", "1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008", "1009"],
  "image_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "configuration_version": "kg-v1.0.0",
  "group_contract_version": 1,
  "phase": "canary"
}
```

The operator must review the exact inventory through the existing protected
operation. The manifest cannot grant steward approval. The runtime checks every
one of the 10–25 distinct PMIDs against `PAPERS` state/final review decision and
the exact `PUBMED_DISCOVERY_RUNS.request_evidence:pmids` scope. Unknown, rejected,
processed, missing-review and outside-scope members block the whole group.
Image, discovery and configuration identities must match the current runtime.
Unknown manifest fields block; provider keys, caller-asserted canary success and
arbitrary queries are not accepted fields. Reports contain capability names,
never manifest contents or credential values.

After the existing extraction preflight succeeds, group checks run before graph,
provider and artifact-client construction. They repeat inside the claim
transaction before its paper update. The claim SELECT additionally restricts its
candidate to the exact manifest PMIDs; existing approval, retry ceiling and graph
receipt exclusion remain in force. Initial group readiness time is recorded by
the runtime, not accepted from the caller.

The existing append-only `attempt_context` diagnostic receives an
`extraction_group` object containing the group/discovery IDs, canonical sorted
PMIDs and their SHA-256 fingerprint, image/configuration/contract identity,
canary phase and extraction/group readiness timestamp. This is not proof that
all pre-topology capabilities were checked. No new table, grant or migration is
introduced, and historical diagnostics are not modified.

Any existing attempt context for the group fences another canary, regardless of
attempt status, inventory or identity. Failed, reserved or partially completed
attempts require an owner-reviewed recovery path; this slice does not create one.
Do not select a new group ID merely to bypass that fence. The existing protected
one-shot concurrency boundary remains necessary; this slice does not implement
a distributed group lock or authorize parallel invocations.

`phase: continue` always returns typed `BLOCKED` with capability
`fresh_canary_receipts_and_serving_visibility_not_implemented`, before claim or
provider construction. The follow-up must join authoritative same-group canary
attempt completion after readiness, matching image/configuration/contract,
graph/artifact/content receipts and completed corpus admission. It must also
prove provider-free visibility through the actual serving query. Evidence must
not be reused across groups; identity changes invalidate it. There is no
time-based reuse window.

Private-network readiness before temporary topology mutation remains unproved
without an approved existing execution surface. Host secret checks were delivered
separately in merged DATA PR #543. KG13 grounded-answer QA is a separate acceptance criterion.
This slice does not complete KG15 or authorize production extraction/deployment.
