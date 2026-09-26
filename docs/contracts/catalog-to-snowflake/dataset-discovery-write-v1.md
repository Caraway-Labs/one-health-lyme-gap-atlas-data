# Dataset Discovery write contract v1 (draft)

Data #449 owns these procedures and the `DATASET_DISCOVERY` tables. This draft starts with `SP_CREATE_RUN`; candidate outcome, recommendation bundle, finalization, review and handoff procedures remain separate work. No migration is approved for application while data #454 or ADR 0041 approval is open.

## Create-run request

`SP_CREATE_RUN(operation_key, requested_run_id, retry_of_run_id, metadata_json)` returns a receipt with `run_id`, `operation_key`, `retry_of_run_id`, and `request_fingerprint`. The JSON has the typed `RunCreateMetadata` fields from Dataset Discovery, plus `request_fingerprint`. It contains versions and identifiers only. Snowflake sets `started_at` at first commit.

The fingerprint is SHA-256 of the UTF-8, sorted-key, compact JSON serialization of every metadata field except `trace_id` and `host_session_id`. Those transport correlations can change after a lost acknowledgment. The procedure recomputes the digest, rejects unexpected or missing fields, and rejects replay of an operation key with a conflicting digest or retry parent. A reused requested run ID under a different key fails. An explicit retry requires a distinct key/run ID and a terminal retry-eligible parent.

Inside one explicit transaction the procedure updates the pre-created `WRITE_SERIALIZATION` row, reads existing state, inserts or returns the committed run, then commits. Errors roll back. This is a design to be proven with concurrent, independent DEV Snowflake sessions; static tests and local JS syntax checks cannot establish Snowflake lock behavior. The runtime role receives only procedure `USAGE` after owner/security approval and protected migration application, never direct `RUNS` DML.
