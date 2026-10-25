-- DATA #787: timings and shapes for one environment's Atlas API statements.
-- The migration identity owns the schema and the secure view.
-- OH_LYME_{ENV}_READ receives schema USAGE and SELECT on this view only.
-- The API user name is OH_LYME_API_SVC in both DEV and PROD. The session
-- database differs, so each deployment keeps only its own database name.
USE DATABASE {{ DATABASE }};

-- The deployer has CREATE SCHEMA on each isolated database. This view
-- projects account-usage timings for one user and one database. It does
-- not copy statement text, error text, application tags, client addresses,
-- or session identifiers. Login events have no database attribute, so they
-- are not projected here.
CREATE SCHEMA IF NOT EXISTS API_DIAGNOSTICS;

CREATE SECURE VIEW IF NOT EXISTS API_DIAGNOSTICS.API_QUERY_HISTORY_V AS
SELECT query_id,
       query_parameterized_hash,
       query_type,
       user_name,
       role_name,
       warehouse_name,
       warehouse_size,
       start_time,
       end_time,
       total_elapsed_time,
       compilation_time,
       execution_time,
       queued_provisioning_time,
       queued_overload_time,
       bytes_scanned,
       rows_produced,
       execution_status,
       error_code
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE user_name = 'OH_LYME_API_SVC'
  AND database_name = '{{ DATABASE }}';

GRANT USAGE ON SCHEMA API_DIAGNOSTICS TO ROLE OH_LYME_{{ ENV }}_READ;
GRANT SELECT ON VIEW API_DIAGNOSTICS.API_QUERY_HISTORY_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
