# 0048: Text-free Atlas API query history

Status: Proposed
Date: 2026-10-24
Amended: 2026-10-25
Decision owner: Atlas product and data engineering
Issue: DATA #787
Parent: API #335

## Context

The production Atlas API connects to Snowflake as service user `OH_LYME_API_SVC` with role `OH_LYME_PROD_READ`. The API repository configures the same user for DEV: `.env.example` sets `SNOWFLAKE_USER=OH_LYME_API_SVC` with `OH_LYME_DEV_READ` and `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, and `.do/app.yaml` sets `SNOWFLAKE_USER=OH_LYME_API_SVC` with `OH_LYME_PROD_READ` and `ONE_HEALTH_LYME_GAP_ATLAS_PROD`. The connector sets the session database from that setting (`snowflake_connection.connection_parameters`). Slow API calls cannot be tied to that user's statements from another role. The API binds values client-side, so account-usage statement text contains user literals such as chat questions and feedback text.

`SNOWFLAKE.ACCOUNT_USAGE` is account-wide. A view in the DEV database that filters only on `USER_NAME` would return the same user's PROD statements to `OH_LYME_DEV_READ`.

ADR 0030 keeps one read-only role per environment, `OH_LYME_{ENV}_READ`, reached by `ATLAS_DEV_READ` and `ATLAS_PROD_READ`. V137 already uses a secure view, owned by the migration identity, as the pattern for a bounded READ projection. Governed procedures that must not cross environments compare `CURRENT_DATABASE()` with `ONE_HEALTH_LYME_GAP_ATLAS_DEV` or `ONE_HEALTH_LYME_GAP_ATLAS_PROD`. Ordinary governed views are isolated because their base tables already live in the environment database.

## Decision

Create schema `API_DIAGNOSTICS` and one secure view with forward-only migration V168, executed by `OH_LYME_{ENV}_MIGRATION_DEPLOYER`:

- `API_DIAGNOSTICS.API_QUERY_HISTORY_V` over `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`

The view keeps rows whose `USER_NAME` is `OH_LYME_API_SVC` and whose `DATABASE_NAME` is the database the migration is applied to. The predicate is `database_name = '{{ DATABASE }}'`. The migration runner substitutes `ONE_HEALTH_LYME_GAP_ATLAS_DEV` or `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, the same literal governed procedures compare with `CURRENT_DATABASE()`. The predicate is fixed in that environment's view. It is not `CURRENT_DATABASE()` at read time, so a session pointed at another database cannot widen the rows. `DATABASE_NAME` is the session database recorded for the statement. The API sets that database at connect time and checks it in the session baseline. Rows with a null session database are omitted.

The view projects `QUERY_ID`, `QUERY_PARAMETERIZED_HASH`, `QUERY_TYPE`, `USER_NAME`, `ROLE_NAME`, `WAREHOUSE_NAME`, `WAREHOUSE_SIZE`, `START_TIME`, `END_TIME`, `TOTAL_ELAPSED_TIME`, `COMPILATION_TIME`, `EXECUTION_TIME`, `QUEUED_PROVISIONING_TIME`, `QUEUED_OVERLOAD_TIME`, `BYTES_SCANNED`, `ROWS_PRODUCED`, `EXECUTION_STATUS`, and `ERROR_CODE`. `DATABASE_NAME` is a filter only.

`OH_LYME_{ENV}_READ` receives `USAGE` on `API_DIAGNOSTICS` and `SELECT` on this view. No other privilege is granted. No new role, user, or write path is introduced.

`ACCOUNT_USAGE` can lag by up to about 45 minutes. That lag is accepted for this diagnostic surface. The [runbook](../operations/api-diagnostics-history.md) states it for operators.

## Query tag

`QUERY_TAG` is not projected. The API sets it at connect time to the constant `one-health-lyme-gap-atlas` (`snowflake_connection.QUERY_TAG`). That value is the same for every API statement in both environments, so it does not separate calls. The column is application-set free text: a later session can replace it with a question, feedback, or other user text. Omitting it keeps that text out of the READ projection. `QUERY_PARAMETERIZED_HASH` remains the statement-shape key.

## Login history

`API_LOGIN_HISTORY_V` is not created. `SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY` has no database, role, or warehouse column. A login is recorded before the session database is selected, and DEV and PROD share `OH_LYME_API_SVC`. A view filtered only by user name would show production logins to a DEV reader. Joining logins to later statements would use session identifiers, which this surface does not expose, and would drop failed logins and logins that never issue a statement. Those are the login events that leave no query row. Login investigation stays with the account owner and is not part of `OH_LYME_{ENV}_READ`.

## Deliberately not exposed

The view does not select `QUERY_TEXT`, `QUERY_TAG`, `ERROR_MESSAGE`, client IP, session identifiers, or any column outside the list above. `QUERY_PARAMETERIZED_HASH` identifies statement shape without the bound literals. `ERROR_CODE` identifies a failure class without the error string. Readers of the secure view do not receive `SELECT` on `SNOWFLAKE.ACCOUNT_USAGE`.

## Operator prerequisite

The migration identity cannot create this view until it can read `QUERY_HISTORY`. The account owner runs the grant below once per environment, before V168, as `ACCOUNTADMIN`. It is not part of V168, not a repository script, and not an agent action.

Preferred grant, issued to the migration role in that environment (`OH_LYME_DEV_MIGRATION_DEPLOYER` or `OH_LYME_PROD_MIGRATION_DEPLOYER`):

```sql
GRANT DATABASE ROLE SNOWFLAKE.GOVERNANCE_VIEWER
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
```

Repeat that statement for `OH_LYME_PROD_MIGRATION_DEPLOYER` before the production migration. `GOVERNANCE_VIEWER` is what makes `QUERY_HISTORY` readable. This migration does not read `LOGIN_HISTORY`, so no login-history database role is required.

Fallback, only if that database role cannot be granted in this account:

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
```

Use the production migration role in the production account grant. Do not grant either form to `OH_LYME_{ENV}_READ`, the API user, or a runtime role.

## Privacy trade-off

The secure view hides statement text from the READ role. The prerequisite grant does not. `SNOWFLAKE.GOVERNANCE_VIEWER` lets `OH_LYME_{ENV}_MIGRATION_DEPLOYER` read all of `ACCOUNT_USAGE` exposed by that database role, including `QUERY_HISTORY.QUERY_TEXT` for every user, not only `OH_LYME_API_SVC` and not only one database. `IMPORTED PRIVILEGES` on database `SNOWFLAKE` is wider still: it lets the deployer read the whole shared `ACCOUNT_USAGE` catalog, including query text. This is an accepted expansion of the existing migration role, not a new role. The migration role must not be used as the routine latency-investigation identity. Routine investigation uses `OH_LYME_{ENV}_READ` and the one view.

## Alternatives considered

Filtering only on `USER_NAME` would show both environments to each reader. Using `CURRENT_DATABASE()` inside the view would follow the reader's session instead of the deployed database. A new diagnostics role would grow the role count that ADR 0030 reduced. Granting READ direct `SELECT` on `ACCOUNT_USAGE` would expose statement text and other users. Selecting `QUERY_TEXT` or `QUERY_TAG` and redacting them in the view still places free text in the view definition and in the owner's query. An owner-rights procedure would add an execution interface for a relational read. Projecting login history without a database attribute would cross the DEV and PROD boundary this amendment removes.

## Consequences

DEV and PROD each need the account-owner grant, then the protected migration path, then a READ-role check that the view returns rows only for `OH_LYME_API_SVC` in that database and that statement text is not in the projection. Rollback is a later reviewed migration that revokes this view's `SELECT` and this schema's `USAGE` from READ, then drops the view and the empty schema. That rollback does not revoke the account-owner prerequisite; revoking `GOVERNANCE_VIEWER` or `IMPORTED PRIVILEGES` is a separate account-owner action. Source rows, semantic releases, and API privileges stay unchanged.
