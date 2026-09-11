# Protected PROD historical CDC onboarding

This runbook creates only the PROD `qtbi-xd4i` evidence candidate required for
an independent steward review. It never copies the DEV decision or runs full
historical ingestion.

1. Merge a green change and record the immutable image digest deployed to DEV.
2. Dispatch `promote-prod.yml` with that exact digest and obtain the protected
   production deployment approval.
3. Verify the four existing source-review views are owned by
   `OH_LYME_PROD_GOVERNED_VIEW_OWNER`. If legacy deployment left them under
   `ACCOUNTADMIN`, perform a separately authorized one-time ownership handoff
   with `COPY CURRENT GRANTS`; do not broaden the Streamlit owner. Apply V049
   as the governed-view owner and V050 as the Streamlit owner. Verify both
   immutable checksums in `SCHEMA_MIGRATIONS`.
4. Deploy `SOURCE_APPROVAL_CONSOLE` under `OH_LYME_PROD_STREAMLIT_OWNER` and
   verify its owner, warehouse, source files, and steward/viewer usage grants.
5. Dispatch `capture-prod-cdc-historical.yml` with the same digest and obtain the
   protected production approval. The one-shot job captures metadata and 25
   ordered sample rows, then restores the prior topology.
6. With the PROD Streamlit-owner role, verify the pending queue/detail records,
   document and schema snapshots, assessment, era limitation, and zero blocking
   material changes.
7. Stop. A human steward reviews and records the PROD decision in Streamlit.

After the decision is recorded, continue only through
[`cdc-historical-prod-ingestion.md`](cdc-historical-prod-ingestion.md). The
onboarding workflow itself remains evidence-only.

Do not invoke `ingest-approved-cdc-historical`, dbt, snapshot publication, or a
schedule in this onboarding step. A failure leaves append-only evidence intact;
restore the prior app specification before retrying. Never print a fetched app
specification because it contains provider-encrypted settings.
