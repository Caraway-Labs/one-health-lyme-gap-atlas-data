# 0049: PubMed query-policy paper approval

Status: Accepted
Date: 2026-10-25
Decision owner: Atlas product and data engineering
Issue: DATA #794
Parent: knowledge-graph #16
Workspace ADR: [0023](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas/blob/main/docs/adr/0023-pubmed-query-policy-paper-approval.md)

## Context

Every discovered PubMed paper waited for a steward decision through
`GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH` before `pipeline pmc-extract` could claim
it. The owner will not review papers manually, so approval was the largest
throughput barrier. Relevance is already bounded by the governed discovery query
(`kg-v1.0.0`), and license, language, PMCID identity, body, budget and fail-closed
checks run automatically at extraction. ADR 0030 and `AGENTS.md` say the pipeline
runtime role must never approve candidates; workspace ADR 0023 amends that rule for
literature only.

## Decision

Add setting `PAPER_APPROVAL_MODE`: `human_review` (default) or `query_policy_v1`.

In `query_policy_v1`, after a discovery run is committed `COMPLETED`,
`discover_pubmed` calls forward-only migration V169's
`GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(P_DISCOVERY_RUN_ID, P_POLICY_VERSION,
P_CORRELATION_ID)` once for that run. Policy `pubmed-query-policy-v1` approves a paper
only when all hold:

1. its PMID is in `request_evidence:pmids` of the named run;
2. that run is `COMPLETED`;
3. the paper is `awaiting_review`;
4. it has a PMCID.

There is no scoring, embedding or model call. Papers without a PMCID stay
`awaiting_review`; the policy never rejects or defers.

Approval writes the same records a steward decision writes: one
`PAPER_REVIEW_DECISIONS` row (`decision='approved'`, `reviewer_username=
'policy:pubmed-query-v1'`, `app_version='pubmed-query-policy-v1'`), one
`PAPER_STATE_EVENTS` row (`reason='paper_policy_approval'`, same actor), and
`PAPERS.state='approved'` with `final_review_decision_id`. The claim query, group
gate, canary receipts, literature-status and retrieval-corpus eligibility need no
change.

The procedure is idempotent (a second call for the run approves nothing), rejects an
unknown or non-`COMPLETED` run and any other policy version with named errors
(-20201 to -20204), and does not consult `APPROVAL_STEWARDS`. It executes as its
creator, the migration identity that owns the knowledge-graph tables, so V169 needs
no table grant and no ownership transfer (which would need account-level `MANAGE
GRANTS`). Moving it to a dedicated owner role is optional hardening. `OH_LYME_{ENV}_RUNTIME`
receives `USAGE` on this procedure only.

Role separation: `SP_RECORD_PAPER_REVIEW_BATCH` and its grants are unchanged. With
`query_policy_v1`, `literature-preflight --operation discover` reports `BLOCKED` if
the runtime lacks the policy `USAGE` grant, holds any grant on the steward
procedure, or can INSERT, UPDATE, DELETE, TRUNCATE or own
`PAPER_REVIEW_DECISIONS`. A regression test pins the migration to one grant, to the
runtime role, with no steward-boundary reference.

Operations:

- `pipeline pubmed-approve-by-policy --discovery-run-id <uuid>` with exactly one of
  `--dry-run` (read-only counts) or `--confirm`. It refuses to run unless
  `PAPER_APPROVAL_MODE=query_policy_v1`.
- If the approval call fails after discovery, the run stays `COMPLETED`, the result
  carries `policy_approval.status=FAILED` with only the exception class, and
  `pubmed-discover` exits non-zero. The command above repairs it.
- `literature-status` reports `decision_sources` (`approved_by_policy`,
  `approved_by_steward`) from `PAPER_STATE_EVENTS`, or `NOT_ATTRIBUTED` if unreadable.
- DEV discovery (`.do/app.yaml`) sets `query_policy_v1`. The PROD one-shot workflow
  takes a `paper_approval_mode` input, default `human_review`, applied to discover
  only. The extraction worker always runs `human_review`.

## Consequences

- Approval is no longer a throughput barrier. Extraction remains one paper per run.
- A paper that loosely matches the governed query (for example a passing Lyme
  mention) can now be extracted and spend budget; the per-paper reservation and the
  daily and monthly caps are the standing limit.
- No procedure withdraws an `approved` paper before extraction. The steward procedure
  rejects only `awaiting_review`, `deferred` and retry states. A withdraw procedure
  is a recommended follow-up.
- The runtime role can approve papers only through this bounded procedure.

## Alternatives considered

Keep human review; metadata scoring, embedding similarity, a trained classifier or a
cheap model triage for an ambiguous band; sampling-based audit. See workspace ADR 0023.

## Rollout and rollback

Merge with default `human_review`. Apply V169 through the protected DEV path, enable
`query_policy_v1` for DEV discovery, and verify one bounded run. PROD enablement is a
separate owner-approved workflow input and is not part of this decision. Roll back by
setting `PAPER_APPROVAL_MODE=human_review`; approved papers stay approved and all
decision records are retained.

## Links

- Migration `V169__paper_policy_approval.sql`; `src/lyme_gap_atlas_data/paper_policy.py`
- `tests/test_paper_policy.py`
- ADR 0030 (amended), ADR 0027, `docs/operations/snowflake-stable-role-model.md`
- Workspace ADR 0023; DATA #794; knowledge-graph #16
