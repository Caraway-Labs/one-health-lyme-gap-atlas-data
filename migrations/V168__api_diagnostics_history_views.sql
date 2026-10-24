-- DATA #787: timings and shapes for the Atlas API service user.
-- The migration identity owns the schema and the two secure views.
-- OH_LYME_{ENV}_READ receives schema USAGE and SELECT on these views only.
-- The API user name is OH_LYME_API_SVC in both DEV and PROD.
USE DATABASE {{ DATABASE }};

-- The deployer has CREATE SCHEMA on each isolated database. These views
-- project account-usage timings for one user. They do not copy statement
-- text, error text, client addresses, or session identifiers.
CREATE SCHEMA IF NOT EXISTS API_DIAGNOSTICS;

CREATE SECURE VIEW IF NOT EXISTS API_DIAGNOSTICS.API_QUERY_HISTORY_V AS
SELECT query_id,
       query_tag,
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
WHERE user_name = 'OH_LYME_API_SVC';

CREATE SECURE VIEW IF NOT EXISTS API_DIAGNOSTICS.API_LOGIN_HISTORY_V AS
SELECT event_timestamp,
       event_type,
       user_name,
       reported_client_type,
       first_authentication_factor,
       is_success,
       error_code
FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
WHERE user_name = 'OH_LYME_API_SVC';

GRANT USAGE ON SCHEMA API_DIAGNOSTICS TO ROLE OH_LYME_{{ ENV }}_READ;
GRANT SELECT ON VIEW API_DIAGNOSTICS.API_QUERY_HISTORY_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
GRANT SELECT ON VIEW API_DIAGNOSTICS.API_LOGIN_HISTORY_V
  TO ROLE OH_LYME_{{ ENV }}_READ;
