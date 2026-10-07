# January diagnostic with verified Standard-edition capabilities

This bounded continuation uses the existing January 2025 membership exporter,
selected run `c2eb2146-005d-44d2-bac4-e2805ca42577`, protected DEV runtime,
and reviewed-main workflow. It does not acquire source inputs, write Snowflake,
publish a release, change settings/grants, or execute historical expansion.

An owner-verified AWS Standard-edition Account Details record can establish
that multi-cluster warehouses and Query Acceleration Service are unavailable.
See Snowflake's [multi-cluster requirements](https://docs.snowflake.com/en/user-guide/warehouses-multicluster)
and [QAS requirements](https://docs.snowflake.com/en/user-guide/query-acceleration-service).
This is an entitlement cost bound, not observed `max_cluster_count=1` or
`enable_query_acceleration=false`. Missing, null and zero SHOW fields remain
unchanged in the diagnostic receipt. Positive contradictory settings block.

The existing `diagnostic_budget_evidence` input accepts an optional
`standard_capability_evidence` object containing exactly:

- `edition`: `STANDARD`; `cloud`: `AWS`
- `account_locator_sha256`: SHA-256 of the uppercase verified account locator
- `verified_by` and timezone-qualified `verified_at` (at most 24 hours old)
- `evidence_reference`: `OWNER_SNOWSIGHT_ACCOUNT_DETAILS`

Keep the actual account identifiers and owner verification privately. Independent
review must reconcile that record with the redacted dispatch input; schema
validation alone does not authenticate an owner statement. The first existing
identity query additionally reads `CURRENT_ACCOUNT()` and verifies the binding
and cloud before SHOW or membership reads. Fresh SHOW still verifies the exact
warehouse, XS size, Standard type, supported generation and auto-suspend ≤60s.
Without edition evidence, explicit one-cluster and disabled-QAS checks remain.

Retain both earlier full forecasts: **US$4.94375**, independently of elapsed
time or actual billing. The approved total ceiling is **US$7**. At the reviewed
US$6/credit public forecast, the existing 50-second execution plus conservatively
reserved 15 seconds, two 60-second XS idle tails and US$1 noncompute allowance
reserve US$1.8929167 more, or **US$6.8366667 cumulatively**. Higher prices shorten
or block execution. This remains a forecast, not an invoice.

The watchdog stays at ≤50 seconds including connection, ≤40 SQL statements,
with 60 seconds reserved for cleanup/upload inside the five-minute job. No
new SDK/API dependency, setup query, property GET, retry, role fallback or
warehouse change is introduced. Existing remote-result download refusal stays.

Next: independent review and exact-head quality checks; reconcile fresh main;
one explicitly bounded dispatch using that reviewed main; inspect the resulting
receipt. A successful workflow does not establish membership export success.
Full frozen membership, donor/lineage/storage parity, protected publication and
actual intended API-reader readback remain separate acceptance gates. DATA #443
and API #84 remain open until their applicable delivery criteria are evidenced.
