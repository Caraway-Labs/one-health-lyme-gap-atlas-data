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

## Read-only attempt, graph and artifact receipt seam

`inspect_group_canary_receipts(group, cursor)` accepts an existing authorized
Snowflake cursor and a parsed group identity. It makes only two bounded SELECTs;
it does not construct a connection, invoke a provider, claim a paper or mutate
history. There is no CLI/workflow activation or caller success assertion.

The first projection preserves missing joins and rejects zero or multiple group
attempt contexts. The authoritative context must match the exact group inventory
and fingerprint, discovery, image, extraction method and group contract. The
attempt must be completed, the paper processed with a steward decision, and the
canary PMID must remain in the exact authoritative discovery scope. Aware start
and finish timestamps must establish completion after that group's recorded
extraction/group readiness. There is no age-based reuse allowance.

The second projection requires exactly one receipt for that extraction attempt
and an exact artifact-ID/PMID join to `PMC_FULL_TEXT_ARTIFACTS`. Paper/PMC identity,
nonempty artifact provenance, valid source/contribution hashes and positive
graph counts must match. Artifact admission must follow group readiness and
precede the attempt; graph publication must fall within that completed attempt.
Missing or ambiguous joins, stale chronology, identity changes and read failures
return typed sanitized blockers. Reports omit object keys, license URLs, content
and exception bodies. This is ledger lineage verification, not a fresh download
or revalidation of artifact bytes/license policy.

Successful lineage reports `receipt_readiness: READY` only for scope
`same_group_attempt_graph_artifact_receipts`. Overall `status` always remains
`BLOCKED`, with corpus admission, actual serving visibility and full pre-topology
readiness explicitly `NOT_CHECKED`, and continuation still unimplemented. The
runtime's existing `phase: continue` denial is unchanged. The remaining corpus
join must bind a fresh completed build and its exact canary units to this receipt
lineage; the serving seam must prove provider-free visibility through the actual
query. Private-network proof still needs an approved existing execution surface.
Offline fixture success is not production evidence or authorization to run.
