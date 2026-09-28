# Dataset Discovery write contract v1 (draft)

Data #449 owns these procedures and the `DATASET_DISCOVERY` tables. This draft includes `SP_CREATE_RUN`, `SP_RECORD_CANDIDATE_OUTCOME`, and `SP_FINALIZE_RUN`; recommendation bundle, review and handoff procedures remain separate work. No migration is approved for application while data #454 or ADR 0041 approval is open.

## Create-run request

`SP_CREATE_RUN(operation_key, requested_run_id, retry_of_run_id, metadata_json)` returns a receipt with `run_id`, `operation_key`, `retry_of_run_id`, and `request_fingerprint`. The JSON has the typed `RunCreateMetadata` fields from Dataset Discovery, plus `request_fingerprint`. It contains versions and identifiers only. Snowflake sets `started_at` at first commit.

The fingerprint is SHA-256 of the UTF-8, sorted-key, compact JSON serialization of every metadata field except `trace_id` and `host_session_id`. Those transport correlations can change after a lost acknowledgment. The procedure recomputes the digest, rejects unexpected or missing fields, and rejects replay of an operation key with a conflicting digest or retry parent. A reused requested run ID under a different key fails. An explicit retry requires a distinct key/run ID and a terminal retry-eligible parent.

Inside one explicit transaction the procedure updates the pre-created `WRITE_SERIALIZATION` row, reads existing state, inserts or returns the committed run, then commits. Errors roll back. This is a design to be proven with concurrent, independent DEV Snowflake sessions; static tests and local JS syntax checks cannot establish Snowflake lock behavior. The runtime role receives only procedure `USAGE` after owner/security approval and protected migration application, never direct `RUNS` DML.

## Candidate outcome request

`SP_RECORD_CANDIDATE_OUTCOME(request_json)` accepts the exact typed `CandidateOutcomeReceipt`: operation/run/resource keys, catalog dataset and resource IDs, evidence snapshot, outcome and optional reason code. It returns that receipt. Within the same serialized transaction, it returns an identical prior operation, rejects conflicting replay or a second outcome for the run/resource, requires an open run with the same snapshot, and verifies candidate IDs against `V_CANDIDATE_SUMMARY` for that snapshot. The outcome ID is a deterministic SHA-256 of its operation key. Untrusted free text cannot enter `outcome` or `reason_code`; only bounded uppercase codes are accepted. The runtime receives procedure `USAGE` only after the same approval and protected migration gates.

DEV forward migration V120 adds an optional, allowlisted `decision_record` to the
same candidate-outcome transaction and receipt. It records model/config/prompt
identities, semantic task, classification, relationship, dimension values and
observation IDs, unknown field names, validator code, abstention reason, and
final outcome. It rejects unexpected keys, unbounded free text, and a decision
whose final outcome differs from the outcome row. Exact operation-key replay
compares the normalized stored decision; conflicting replay fails closed.
Historical V107 checksums are unchanged. Recommendation versions already retain
validated analysis and ranking; V120 addresses unsuccessful decisions without
retaining prompts, model reasoning, raw catalog payloads, or secret values.

DEV forward migration V121 replaces only the candidate-outcome procedure with
`COPY GRANTS`; V119 and V120 remain immutable. The existing `decision_record`
VARIANT carries bounded provider invocation, transport, parse, validator
stage/code/path, token usage, response schema version, and SHA-256 response
fingerprint. It also preserves safe parsed classification, dimensions, citations,
and unknown field identifiers when evidence validation rejects a typed result.
The procedure rejects unexpected fields, incoherent call sequencing, unbounded
values, and conflicting operation-key replay in the same serialized transaction.
It never accepts raw response text, prompts, credentials, or protected metadata.

DEV forward migration V122 replaces that procedure with `COPY GRANTS`, retaining
the same atomic outcome receipt and replay checks. Four optional completion facts
are allowlisted: normalized provider status, SDK-enumerated incomplete reason,
SDK-enumerated error code, and SHA-256 of the provider response ID. The procedure
rejects unrecognized values and never stores provider error messages, literal
response IDs, response bodies, prompts, or hidden reasoning. No table column is
added; V119-V121 and their ledger entries remain immutable.

DEV forward migration V119 corrects the bounded observation projection. For
Data.gov, `issued`, `modified`, `spatial`, `temporal`, `license`, and
`accessLevel` fall back to the retained `metadata_payload.catalog_record.dcat`
path when the normalized top-level key is absent. Explicit length bounds make
oversize fields NULL. The view also exposes bounded keyword/theme text,
resource/distribution title, role, type, URL, purpose, media/format, parent
dataset ID, catalog record ID, and public harvest-documentation locator. It
preserves observation identity and grants with `COPY GRANTS`, without exposing
the nested raw record or private artifact bytes. These DEV-only migrations do
not authorize PROD application.

## Terminal finalization request

`SP_FINALIZE_RUN(request_json)` accepts the exact typed `RunFinalizationReceipt`: operation/run IDs, terminal status, processed and recommendation counts, allowlisted nonnegative budget usage counters, and optional stop reason. It acquires the same serialization row, returns an identical prior finalization, and rejects a conflicting replay or an already terminal run. Before updating `RUNS`, it recomputes processed and recommendation counts from committed candidate outcomes and recommendation versions. It stores the terminal status, completion time, finalization key, stop reason and usage counters in one transaction. `V_FINALIZATION_RECEIPTS` exposes the receipt for lost-acknowledgment recovery. A partially persisted run is never labeled successful merely because the client requested success.
