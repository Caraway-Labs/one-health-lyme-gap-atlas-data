# Atlas API query and login history

Use this runbook to investigate Atlas API Snowflake latency from timings and shapes. It reads `API_DIAGNOSTICS.API_QUERY_HISTORY_V` and `API_DIAGNOSTICS.API_LOGIN_HISTORY_V`, created by V168. The decision record is [ADR 0048](../adr/0048-api-diagnostics-history-views.md).

## Connection

| Environment | Connection | Database | Warehouse |
| --- | --- | --- | --- |
| DEV | `ATLAS_DEV_READ` | `ONE_HEALTH_LYME_GAP_ATLAS_DEV` | The warehouse already selected for that READ connection |
| PROD | `ATLAS_PROD_READ` | `ONE_HEALTH_LYME_GAP_ATLAS_PROD` | `COMPUTE_WH` |

Both connections use the existing `OH_LYME_{ENV}_READ` role. Do not use `ACCOUNTADMIN`, the migration role, or the API service user for this investigation.

Set the database and warehouse before the queries below. Replace `:window_start`, `:window_end`, and `:row_limit` with the investigation bounds. Do not paste statement text, feedback, or chat text into these queries. The views do not contain those fields.

## Accepted lag

`SNOWFLAKE.ACCOUNT_USAGE` can lag by up to about 45 minutes. A statement or login that just finished can be absent. That lag is accepted. Wait for the lag window before treating an empty result as evidence that no statement ran. Elapsed-time columns are milliseconds.

Both views are already limited to `OH_LYME_API_SVC`. A login has no query row. Use the login view for authentication time and the query view for statement time.

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
       query_tag,
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

## Login count per hour

```sql
SELECT DATE_TRUNC('hour', event_timestamp) AS hour_start,
       COUNT(*) AS login_count
FROM API_DIAGNOSTICS.API_LOGIN_HISTORY_V
WHERE event_timestamp >= :window_start
  AND event_timestamp < :window_end
GROUP BY hour_start
ORDER BY hour_start;
```

## Failed logins

`IS_SUCCESS` is the account-usage success flag. Failed rows use the value `NO`.

```sql
SELECT event_timestamp,
       event_type,
       reported_client_type,
       first_authentication_factor,
       error_code
FROM API_DIAGNOSTICS.API_LOGIN_HISTORY_V
WHERE is_success = 'NO'
  AND event_timestamp >= :window_start
  AND event_timestamp < :window_end
ORDER BY event_timestamp;
```
