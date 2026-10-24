# 0048: Text-free Atlas API query and login history

Status: Proposed
Date: 2026-10-24
Decision owner: Atlas product and data engineering
Issue: DATA #787
Parent: API #335

## Context

The production Atlas API connects to Snowflake as service user `OH_LYME_API_SVC` with role `OH_LYME_PROD_READ`. The API repository configures the same user for DEV: `.env.example` sets `SNOWFLAKE_USER=OH_LYME_API_SVC` with `OH_LYME_DEV_READ` and `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, and `.do/app.yaml` sets `SNOWFLAKE_USER=OH_LYME_API_SVC` with `OH_LYME_PROD_READ` and `ONE_HEALTH_LYME_GAP_ATLAS_PROD`. Slow API calls cannot be tied to that user's statements from another role, and a fresh login leaves no statement at all. The API binds values client-side, so account-usage statement text contains user literals such as chat questions and feedback text.

ADR 0030 keeps one read-only role per environment, `OH_LYME_{ENV}_READ`, reached by `ATLAS_DEV_READ` and `ATLAS_PROD_READ`. V137 already uses a secure view, owned by the migration identity, as the pattern for a bounded READ projection.

## Decision

Create schema `API_DIAGNOSTICS` and two secure views with forward-only migration V168, executed by `OH_LYME_{ENV}_MIGRATION_DEPLOYER`:

- `API_DIAGNOSTICS.API_QUERY_HISTORY_V` over `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`
- `API_DIAGNOSTICS.API_LOGIN_HISTORY_V` over `SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY`

Both views keep only rows whose `USER_NAME` is `OH_LYME_API_SVC`. The names match, so the filter is a literal rather than a new template variable.

The query view projects `QUERY_ID`, `QUERY_TAG`, `QUERY_PARAMETERIZED_HASH`, `QUERY_TYPE`, `USER_NAME`, `ROLE_NAME`, `WAREHOUSE_NAME`, `WAREHOUSE_SIZE`, `START_TIME`, `END_TIME`, `TOTAL_ELAPSED_TIME`, `COMPILATION_TIME`, `EXECUTION_TIME`, `QUEUED_PROVISIONING_TIME`, `QUEUED_OVERLOAD_TIME`, `BYTES_SCANNED`, `ROWS_PRODUCED`, `EXECUTION_STATUS`, and `ERROR_CODE`.

The login view projects `EVENT_TIMESTAMP`, `EVENT_TYPE`, `USER_NAME`, `REPORTED_CLIENT_TYPE`, `FIRST_AUTHENTICATION_FACTOR`, `IS_SUCCESS`, and `ERROR_CODE`.

`OH_LYME_{ENV}_READ` receives `USAGE` on `API_DIAGNOSTICS` and `SELECT` on these two views. No other privilege is granted. No new role, user, or write path is introduced.

`ACCOUNT_USAGE` can lag by up to about 45 minutes. That lag is accepted for this diagnostic surface. The [runbook](../operations/api-diagnostics-history.md) states it for operators.

## Deliberately not exposed

The views do not select `QUERY_TEXT`, `ERROR_MESSAGE`, client IP, session identifiers, or any column outside the lists above. `QUERY_PARAMETERIZED_HASH` identifies statement shape without the bound literals. `ERROR_CODE` identifies a failure class without the error string. Readers of the secure views do not receive `SELECT` on `SNOWFLAKE.ACCOUNT_USAGE`.

## Operator prerequisite

The migration identity cannot create these views until it can read the underlying account-usage views. The account owner runs the grants below once per environment, before V168, as `ACCOUNTADMIN`. They are not part of V168, not a repository script, and not an agent action.

Preferred grants, issued to the migration role in that environment (`OH_LYME_DEV_MIGRATION_DEPLOYER` or `OH_LYME_PROD_MIGRATION_DEPLOYER`):

```sql
GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
GRANT DATABASE ROLE SNOWFLAKE.SECURITY_VIEWER
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
```

Repeat the same two statements for `OH_LYME_PROD_MIGRATION_DEPLOYER` before the production migration. `GOVERNANCE_VIEWER` is what makes `QUERY_HISTORY` readable. `SECURITY_VIEWER` is what makes `LOGIN_HISTORY` readable. Both are required.

Fallback, only if those database roles cannot be granted in this account:

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
```

Use the production migration role in the production account grant. Do not grant either form to `OH_LYME_{ENV}_READ`, the API user, or a runtime role.

## Privacy trade-off

The secure views hide statement text from the READ role. The prerequisite grant does not. `SNOWFLAKE.GOVERNANCE_VIEWER` lets `OH_LYME_{ENV}_MIGRATION_DEPLOYER` read all of `ACCOUNT_USAGE` exposed by that database role, including `QUERY_HISTORY.QUERY_TEXT` for every user, not only `OH_LYME_API_SVC`. `SNOWFLAKE.SECURITY_VIEWER` likewise lets that role read login history beyond the seven projected columns, including client addresses and `ERROR_MESSAGE`. `IMPORTED PRIVILEGES` on database `SNOWFLAKE` is wider still: it lets the deployer read the whole shared `ACCOUNT_USAGE` catalog, including query text. This is an accepted expansion of the existing migration role, not a new role. The migration role must not be used as the routine latency-investigation identity. Routine investigation uses `OH_LYME_{ENV}_READ` and the two views.

## Alternatives considered

A new diagnostics role would grow the role count that ADR 0030 reduced. Granting READ direct `SELECT` on `ACCOUNT_USAGE` would expose statement text and other users. Selecting `QUERY_TEXT` and redacting it in the view still places literals in the view definition and in the owner's query. An owner-rights procedure would add an execution interface for a relational read. Leaving the history visible only to the API user preserves the current blind spot.

## Consequences

DEV and PROD each need the account-owner grant, then the protected migration path, then a READ-role check that the two views return rows for `OH_LYME_API_SVC` and that statement text is not in the projection. Rollback is a later reviewed migration that revokes these two `SELECT` grants and schema `USAGE` from READ, then drops the views and the empty schema. That rollback does not revoke the account-owner prerequisite; revoking `GOVERNANCE_VIEWER`, `SECURITY_VIEWER`, or `IMPORTED PRIVILEGES` is a separate account-owner action. Source rows, semantic releases, and API privileges stay unchanged.
