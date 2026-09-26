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

Grant `OH_LYME_{{ ENV }}_READ` `USAGE` on exactly two `EXECUTE AS OWNER`
procedures - `GOVERNANCE.SP_SUBMIT_USER_FEEDBACK` and
`GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT` - and `SELECT` on
`GOVERNANCE.V_USER_FEEDBACK_ANALYST` only. Do not grant table DML or base-table
`SELECT` on feedback relations to `READ` or `RUNTIME`. Owner triage, reveal,
and operator redaction grants land in a later story (#130), not here.

This is a deliberate, narrow exception to ADR 0030's direct-DML read-only
semantics for `READ`. The exception rests on all five points below:

1. **No sixth role.** The API already uses `OH_LYME_{ENV}_READ`. A new user,
   key, or secret is not justified for two procedures.
2. **`EXECUTE AS OWNER` plus `USAGE` is least privilege.** The caller cannot
   pass SQL or name tables. The procedure re-validates arguments and writes only
   the feedback relations.
3. **`READ` may invoke only** `SP_SUBMIT_USER_FEEDBACK` and
   `SP_REDACT_FEEDBACK_FOR_ACCOUNT`, and may `SELECT` only
   `V_USER_FEEDBACK_ANALYST`.
4. **This precedent does not permit arbitrary future mutation procedures on
   `READ`.** Each new grant needs its own ADR.
5. **Introduce a dedicated API mutation role** if the mutation surface grows
   beyond these two procedures or the API moves past one process.

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
  tables, the two procedures, and the analyst view.
- Static grant tests lock the READ exception surface.
- Expanding writes beyond these two procedures requires a new ADR and, when
  the surface grows or topology scales, a dedicated mutation role.
