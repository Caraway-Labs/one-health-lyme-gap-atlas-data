-- Additive, scoped transport for future bounded set-oriented ingestion.
-- Existing V069/V103 tables, rows, migration state, and governed artifacts stay intact.
USE DATABASE {{ DATABASE }};

CREATE STAGE IF NOT EXISTS GOVERNANCE.INGESTION_BULK_STAGE
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
    FILE_FORMAT = (TYPE = JSON MULTI_LINE = FALSE COMPRESSION = AUTO);

GRANT READ, WRITE ON STAGE GOVERNANCE.INGESTION_BULK_STAGE
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
