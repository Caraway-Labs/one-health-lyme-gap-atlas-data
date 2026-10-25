# Atlas API query history

Use this runbook to investigate Atlas API Snowflake statement latency from timings and shapes. It reads `API_DIAGNOSTICS.API_QUERY_HISTORY_V`, created by V168. The decision record is [ADR 0048](../adr/0048-api-diagnostics-history-views.md).

## Connection

| Environment | Connection | Database | Warehouse |
| --- | --- | --- | --- |
| DEV | `ATLAS_DEV_READ` | `ONE_HEALTH_LYME_GAP_ATLAS_DEV` | The warehouse already selected for that READ connection |
| PROD | `ATLAS_PROD_READ` | `ONE_HEALTH_LYME_GAP_ATLAS_PROD` | `COMPUTE_WH` |

Both connections use the existing `OH_LYME_{ENV}_READ` role. Do not use `ACCOUNTADMIN`, the migration role, or the API service user for this investigation.

Set the database and warehouse before the queries below. Replace `:window_start`, `:window_end`, and `:row_limit` with the investigation bounds. Do not paste statement text, feedback, or chat text into these queries. The view does not contain those fields.

## What the view already limits

The view keeps statements for `OH_LYME_API_SVC` whose session database is the database where that view was created. The DEV view does not return PROD statements, and the PROD view does not return DEV statements. A statement with no session database is omitted. The view does not project `QUERY_TAG`. That column is application-set free text; the current API value is one constant for every environment and does not separate calls. `QUERY_PARAMETERIZED_HASH` is the shape key.

Login history is not in this view. `LOGIN_HISTORY` has no database, role, or warehouse column. The shared API user records a login before a database is selected, so those rows cannot be limited to one environment without mixing them. Do not query login history with `OH_LYME_{ENV}_READ`.

## Deployment

The account-owner grant in [ADR 0048](../adr/0048-api-diagnostics-history-views.md) comes before V168. DEV dispatch of `deploy-dev.yml` names only this migration in `expected_pending_json`. Pending V155 and V157–V161 are emitted as `held_back_migrations` and stay unapplied. PROD dispatch of `promote-prod.yml` uses `protected_intelligence_prerequisite=true` and the single allow-listed V168 object. Its source checksum is `18fd6c1ec8b2b6bf483a2e76ce2be08074a31038d6131b7d2a23a8456676a3f6`.

```json
[{"version":"V168","filename":"V168__api_diagnostics_history_views.sql","sha256":"18fd6c1ec8b2b6bf483a2e76ce2be08074a31038d6131b7d2a23a8456676a3f6"}]
```

## Accepted lag

`SNOWFLAKE.ACCOUNT_USAGE` can lag by up to about 45 minutes. A statement that just finished can be absent. That lag is accepted. Wait for the lag window before treating an empty result as evidence that no statement ran. Elapsed-time columns are milliseconds.

## Statements per minute for the last 24 hours

```sql
SELECT DATE_TRUNC('minute', start_time) AS minute_start,
       COUNT(*) AS statement_count
FROM API_DIAGNOSTICS.API_QUERY_HISTORY_V
WHERE start_time >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
GROUP BY minute_start
ORDER BY minute_start;
```

## Slowest statements by elapsed time

```sql
SELECT query_id,
       query_parameterized_hash,
       query_type,
       warehouse_name,
       warehouse_size,
       start_time,
       total_elapsed_time
FROM API_DIAGNOSTICS.API_QUERY_HISTORY_V
WHERE start_time >= :window_start
  AND start_time < :window_end
ORDER BY total_elapsed_time DESC
LIMIT :row_limit;
```

## Compilation and queue time breakdown

```sql
SELECT query_id,
       query_parameterized_hash,
       query_type,
       total_elapsed_time,
       compilation_time,
       execution_time,
       queued_provisioning_time,
       queued_overload_time
FROM API_DIAGNOSTICS.API_QUERY_HISTORY_V
WHERE start_time >= :window_start
  AND start_time < :window_end
ORDER BY total_elapsed_time DESC
LIMIT :row_limit;
```

## Error codes

```sql
SELECT execution_status,
       error_code,
       COUNT(*) AS statement_count
FROM API_DIAGNOSTICS.API_QUERY_HISTORY_V
WHERE start_time >= :window_start
  AND start_time < :window_end
GROUP BY execution_status, error_code
ORDER BY statement_count DESC;
```
