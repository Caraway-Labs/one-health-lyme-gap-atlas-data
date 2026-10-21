# PR #714 technical review and merge handoff

Fresh review of `06eb1df06e3be3664af4ee4e209a80ec289748f7` against main
`ce77e47d3ba5d95d465c482d4ac87166202d3dae`, performed from the new isolated
`intelligence-714-review-20261020` worktree. Existing checkouts were not edited.
This technical review is not a GitHub independent approving review or approval
to merge, provision, deploy, create a PROD fixture, delete, or ingest.

## Finding resolved

P2: the synthetic checkpoint probe required only one row and its matching lease
marker. A metadata-only row with no `xml_base64` could therefore pass as a raw
copy and make the later deletion proof vacuous. The probe now additionally
requires nonempty, decodable base64 and the reviewed artifact SHA field; it
returns counts only. A negative regression case rejects a marker-only row
without writing a private plan or reporting success. Actual content SHA256
verification remains part of the separately approved fixture-creation receipt.

## Controls examined

| Control | Review result |
| --- | --- |
| Exact PROD source / bucket / key / database / paired synthetic capture | Existing fixed scope retained; additional eligible EID copies fail inspection |
| Read-only inspection | Installed named-PAT `snow` CLI SELECT; Spaces list/HEAD; no provider writes, guard UPDATE, approval insert or raw retrieval |
| Claim/lease expiry and live aliases | Existing `plan_cleanup` and immutable 30-day leases reused |
| Inventory race | Double snapshot is explicitly non-atomic evidence; execution still revalidates under the existing durable guard |
| Object versions | Version history/delete markers/truncation fail before checkpoint mutation and immediately around DELETE; no version purge added |
| Confirmed object deletion | HEAD absence required; denied access is not absence; idempotent retry retained |
| Authority separation | Dedicated executor, separate approver, V150 handoff and exact-plan approval remain required; human audit explicitly proves no executor identity |
| Normalized/provenance preservation | No normalized item, revision, source or provenance deletion introduced |
| Secrets / output / plan storage | Explicit dedicated key variables, bounded calls, redacted provider errors, exclusive local plan creation; Windows private-directory ACL remains an operator responsibility |
| Migration / public contract / architecture | No migration, role grant, publisher policy or public API change |

No other introduced P1/P2 finding was identified in this scoped review.
The existing retention policy and production gates remain unresolved operational
acceptance, not code-review approval. See the existing
[acceptance audit](data680-rss-acceptance-2026-10-20.md) and
[PROD cleanup runbook](../operations/intelligence-raw-cleanup-prod.md).

Validation and exact-head hosted Quality receipts are recorded in PR #714.
Do not rerun the prior broad Windows suite merely to replace its known deadline
diagnostics; focused changed-boundary tests plus full hosted Linux Quality are
the validation for this increment. No deployment workflow is dispatched.
