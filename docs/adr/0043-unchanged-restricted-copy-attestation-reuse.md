# 0043: Reuse recorded final-copy evidence for unchanged restricted output

Status: Proposed for human governance review
Date: 2026-10-09
Decision owner: Atlas product/data steward and engineering

## Context and decision

The CEO decision at the beginning of DATA #594 authorizes correcting redundant
candidate-specific receipts, while preserving externally binding CDC delivery
obligations. A release identifier alone does not establish a new restricted
source copy. Recognize actual previously recorded evidence only when a previously
PUBLISHED/RETIRED release has identical resource/source/dataset/version/run/artifact
and source attribution/limitations, matching release schema/methodology, and the
same complete derived observation multiset (values, states, geography, time,
retrieval, transformation, quality, limitations and immutable record lineage).

No receipt is copied or created. Changed source versions, changed output, absent
or unusable receipts and inaccessible evidence fail closed. Existing candidate
receipts and all other quality/publication/access checks remain unchanged. V089
is append-only history and is not edited; its owner procedure remains the path
for genuinely new delivery evidence.

This narrowly amends ADR 0033's internal candidate-specific enforcement. It does
not reinterpret or waive the agreement recorded in ADR 0029: CDC receives the
required final copy of resulting publications/presentations. A new external
publication/presentation requires the applicable delivery even if source inputs
are unchanged. Human approval of this policy must confirm that the unchanged
restricted output reused for the NLCD-only append is covered by the retained
delivery; the CEO assertion is not an independently observed database receipt.

## Acceptance, rollout and rollback

Relational regression tests cover unchanged and changed copies, missing/invalid
receipts, candidate versus prior publication status, duplicate/empty output,
zero semantics and mixed current/prior attestations. No grants, new tables,
raw workbook reads or attestation framework are introduced. Protected publication
uses the reviewed implementation commit and existing pinned NLCD manifest after
green CI, governance review and environment approval. Real ledger visibility and
consumer/API acceptance remain execution evidence, separate from these tests.

Rollback retains the previous published release and existing protected rollback
operation; reverting this policy reinstates candidate-specific receipt matching.
No existing receipt or restricted record is changed by deployment or rollback.

Refs: DATA #594 CEO decision; ADR 0029; ADR 0033; V089;
`semantic_release.py::_verify_restricted_final_copy_attestations`.
