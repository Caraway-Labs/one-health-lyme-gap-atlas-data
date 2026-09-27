# 0040: User feedback write boundary on the API read role

Status: Accepted
Date: 2026-09-26
Decision owner: Atlas data stewardship and engineering
Story: Caraway-Labs/one-health-lyme-gap-atlas-data#129 (Epic #63)

## Context

Atlas user feedback (Epic #63) must persist through Snowflake while the
production API continues to authenticate as `OH_LYME_{ENV}_READ`. ADR 0030
documents `READ` as a read-only presentation and audit boundary. Direct table
`INSERT` / `UPDATE` / `DELETE` for `READ` would break that model. A sixth
Snowflake role or service user would add a new identity, key material, and App
Platform secret for two bounded procedures.

Standard Snowflake tables do not enforce `PRIMARY KEY` / `UNIQUE`. Concurrent
inserts from multiple API processes can still create two rows for one
`submission_token`. This repository has no hybrid tables; adopting them would
introduce a new storage engine and transaction-mixing constraints out of
proportion to V1.

## Decision

Grant `OH_LYME_{{ ENV }}_READ` `USAGE` on `EXECUTE AS OWNER` feedback
procedures and `SELECT` on `GOVERNANCE.V_USER_FEEDBACK_ANALYST` only. Do not
grant table DML or base-table `SELECT` on feedback relations to `READ` or
`RUNTIME`. Owner triage, reveal, and operator redaction stay on `OWNER`.

Story #129 approved two procedures. Story #130 / migration V105 adds a third,
account-scoped privacy export. The approved READ capabilities are now:

1. `GOVERNANCE.SP_SUBMIT_USER_FEEDBACK` — submit a feedback record.
2. `GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT` — remove account linkage and
   contact rows for a server-verified account. The submitted message stays.
3. `GOVERNANCE.SP_EXPORT_FEEDBACK_FOR_ACCOUNT` — return only that account's
   category, route, received time, message, and whether a contact email exists.

The export procedure is read-only in product semantics. It still uses
`EXECUTE AS OWNER` because `READ` must not `SELECT` the protected feedback,
contact, or account tables. The API passes only the account id taken from the
verified Supabase token. The procedure does not accept a client-supplied
account id from the feedback request body.

This is a deliberate, narrow exception to ADR 0030's direct-DML read-only
semantics for `READ`. The exception rests on all five points below:

1. **No sixth role yet.** The API already uses `OH_LYME_{ENV}_READ`. A new
   user, key, or secret is not justified for these three bounded procedures.
   The API also cannot use the `OWNER` analyst surface: that role can triage,
   reveal contact, and redact message text. Privacy export must not carry
   those powers.
2. **`EXECUTE AS OWNER` plus `USAGE` is least privilege.** The caller cannot
   pass SQL or name tables. Each procedure re-validates its arguments. Submit
   and linkage removal write only the feedback relations. Export reads only
   the rows whose account link matches the argument and does not return the
   contact email itself.
3. **`READ` may invoke only** `SP_SUBMIT_USER_FEEDBACK`,
   `SP_REDACT_FEEDBACK_FOR_ACCOUNT`, and
   `SP_EXPORT_FEEDBACK_FOR_ACCOUNT`, and may `SELECT` only
   `V_USER_FEEDBACK_ANALYST`. Direct base-table protected reads remain
   forbidden. On the API path, account id arguments come from the verified
   token, not from the browser body.
4. **This precedent does not permit arbitrary future mutation procedures on
   `READ`,** and it does not permit arbitrary future owner-rights procedures
   on `READ`. Each new grant needs its own ADR. Export does not authorize
   reveal, triage, or message redaction for `READ`.
5. **Introduce a dedicated API mutation role** or a protected-data role when the
   mutation surface grows beyond submit and account-linkage removal, when
   protected reads grow beyond this one account-scoped export, or when the
   API moves past one process.

## Atomic mutation

Snowflake Scripting does not commit a procedure as one implicit transaction.
`SP_SUBMIT_USER_FEEDBACK` and `SP_REDACT_FEEDBACK_FOR_ACCOUNT` use an explicit
`BEGIN TRANSACTION` / `COMMIT` around each logical mutation set. On failure the
exception handler executes `ROLLBACK` and returns `status=failed` with
`reason=persistence_failed`. The result object does not include `SQLERRM`,
feedback text, or contact email. A `CONTEXT_JSON` value of `__rollback_probe__`
is reserved for DEV proof: the procedure inserts and then raises inside the
transaction so the caller can observe that no partial row remains. The API
contract cannot emit that string.

## Idempotency invariant

V1 feedback idempotency is correct only while the API runs as exactly one process
on one instance. Standard tables do not enforce uniqueness; hybrid tables were rejected
as a new storage engine. Cross-process races are prevented by the API
single-process lock, not by a primary key. Distributed idempotency is required
before horizontal or multi-worker scaling.

## Privacy and retention

Optional contact and account linkage exist for follow-up and account-rights
deletion. There is no 24-month retention claim and no time-based purge in this
story. `SP_REDACT_FEEDBACK_FOR_ACCOUNT` removes contact and account linkage for
that account and keeps the submitted message. Operator message redaction is a
separate OWNER procedure in #130.

## Consequences

- Migration `V104__user_feedback_submission.sql` creates the four GOVERNANCE
  tables, the submit and linkage-removal procedures, and the analyst view.
- Migration `V105__user_feedback_triage.sql` adds OWNER triage, reveal, and
  message redaction, plus the READ account-scoped export procedure.
- Static grant tests lock the READ exception surface.
- Expanding writes or protected reads beyond the three procedures above
  requires a new ADR and, when the surface grows or topology scales, a
  dedicated mutation or protected-data role.
