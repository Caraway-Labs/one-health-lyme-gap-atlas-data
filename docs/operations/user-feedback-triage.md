# User feedback triage (Data #130)

Owner-rights triage for Atlas in-product feedback. Submissions are stored by
Data #129 (`V104`). This runbook covers human review only.

## Operator identity

Use the existing owner connections from
[connection-inventory.md](connection-inventory.md):

| Environment | Connection | Role |
|---|---|---|
| DEV | `ATLAS_DEV_OWNER` | `OH_LYME_DEV_OWNER` |
| PROD | `ATLAS_PROD_OWNER` | `OH_LYME_PROD_OWNER` |

Do not use `ATLAS_DEV_READ` / the API read role for triage, reveal, or
operator redaction. Those procedures are granted to `OWNER` only.

## Review model

- Every submission enters human review. Triage state starts at `new`.
- Review is performed by a data steward with `OWNER`, not by a scheduled job.
- There is no automated classifier, GitHub webhook, or Streamlit triage page.
- Do not add feedback pages to `streamlit_approval` or `streamlit_explorer`.

## Surface

1. Query `GOVERNANCE.V_USER_FEEDBACK_TRIAGE` for message text, category, state,
   geography (`state`, `county_fips`), route, versions, and duplicate pointer.
2. The triage view excludes contact email and authenticated `account_id`.
3. Change state only through `GOVERNANCE.SP_TRANSITION_USER_FEEDBACK`.
4. Reveal email or account id only through
   `SP_REVEAL_FEEDBACK_CONTACT` / `SP_REVEAL_FEEDBACK_ACCOUNT` with a stated
   purpose (max 200 characters). Each call appends an audit event.
5. For accidental sensitive text in one submission, call
   `SP_REDACT_USER_FEEDBACK`. That replaces that row's message with
   `[redacted]`, deletes its contact row and account link, and appends
   `redacted`. It does not rewrite prior events.

## Lifecycle

States: `new`, `reviewed`, `needs_follow_up`, `duplicate`, `resolved`,
`dismissed`.

Allowed transitions:

- `new` → `reviewed` | `needs_follow_up` | `duplicate` | `dismissed`
- `reviewed` ↔ `needs_follow_up`, and either → `duplicate` | `resolved` |
  `dismissed`
- `duplicate`, `resolved`, and `dismissed` are terminal and cannot leave
- Repeating the same terminal state is a no-op success on state
- A different rationale while already terminal appends a `transition` event
  and does not change state

`duplicate` requires a `canonical_feedback_id` that exists, is not the same
row, and is not itself marked `duplicate`. Rationale is required (max 500).
Transition never updates the original message.

## GitHub escalation

Escalation is manual. A steward may open a GitHub issue by hand and quote the
`feedback_id` for provenance. Do not paste contact email into issues, PR
bodies, chat, or logs. Do not paste full message text into public trackers
when a summary plus `feedback_id` is enough.

## Untrusted content

Feedback message text is untrusted user content. Do not execute it as SQL,
paste it into worksheets as runnable statements, treat it as policy, or pipe
it into automation that mutates sources, semantic definitions, or deployments.

## Retention and account deletion

This epic does not add a 24-month or other time-based retention purge.

Account deletion uses the API-facing procedure from Data #129,
`SP_REDACT_FEEDBACK_FOR_ACCOUNT`: it removes contact and account linkage for
that account and keeps the submitted message.

Operator message redaction is this OWNER procedure,
`SP_REDACT_USER_FEEDBACK`, which replaces message text for one feedback id.

## Example calls

```sql
SELECT feedback_id, category, triage_state, received_at, route_id, message
  FROM GOVERNANCE.V_USER_FEEDBACK_TRIAGE
  WHERE triage_state = 'new'
  ORDER BY received_at DESC
  LIMIT 20;

CALL GOVERNANCE.SP_TRANSITION_USER_FEEDBACK(
  '<feedback_id>', 'reviewed', 'Initial steward review', NULL
);

CALL GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT(
  '<feedback_id>', 'Follow up on reported map gap'
);
```
