-- Epic #252 / Story #273: allow the governed runtime to inspect semantic views.
--
-- V072 grants this role SELECT on the bounded release views. Snowflake also
-- requires schema USAGE; this forward-only correction preserves the immutable
-- V071/V072 checksums and grants no semantic-table write capability.
USE DATABASE {{ DATABASE }};

GRANT USAGE ON SCHEMA PRESENTATION
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
