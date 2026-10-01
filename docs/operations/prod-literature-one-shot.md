# Bounded production PubMed/PMC operations

DATA #497 provides an intentional, protected one-shot execution route for DATA
#495. It does not authorize the +100-paper batch or a production deployment.
The live app's six scheduled jobs remain the persistent topology. A protected
GitHub workflow temporarily adds exactly one `PRE_DEPLOY` job, waits for it,
then restores the captured six-job spec even when the invocation fails. No
literature timer or automatic approval is installed. The temporary spec contains
provider-encrypted values; never print, attach, or commit it.
DigitalOcean [documents deploy-time and scheduled App Platform jobs](https://docs.digitalocean.com/products/app-platform/how-to/manage-jobs/);
the repository already uses this temporary pre-deploy pattern for protected
one-shot production operations.

The live production app currently has no VPC attachment, while its Neo4j
droplet is private at `10.116.0.3` on VPC
`a937d8dd-4ee9-4de2-a8df-b32e7ad4098e`. The temporary preflight and
extraction deployments attach that reviewed VPC; restoration removes the
attachment and returns the exact prior app spec. DigitalOcean documents
[app-spec VPC attachment and removal](https://docs.digitalocean.com/products/app-platform/how-to/enable-vpc/).
This is an app-level network change during the bounded invocation, so the
production reviewer must confirm no other app deployment or scheduled job
operation is in flight before approving it.

## Before the first protected release

Apply the reviewed V134 diagnostic-type migration through the protected
promotion path before running the DATA #528 worker image. Extraction preflight
blocks if the attempt-context and stage-failure contract is absent. Do not
deploy the image first or bypass a blocked preflight.
V134 also adds the discovery-run link to the existing corpus build ledger.
Status reports linked failed builds by build ID (also their correlation ID),
with retryability and next action. Its corpus failure count measures builds,
not papers; historical builds without a discovery link remain unattributed.

1. Merge the reviewed DATA #497 PR through normal governance. Confirm the
   immutable pipeline image digest is active in both DEV and PROD; the workflow
   verifies both active deployments and rejects drift. Do not run the workflow
   from a branch other than `main`.
2. A production owner must configure these **production GitHub environment**
   secrets without printing their values: `NCBI_EMAIL` for discovery;
   `NEO4J_RUNTIME_PASSWORD`, `GROQ_API_KEY`, and `OPENAI_API_KEY` for extraction.
   `NCBI_API_KEY` is optional. Existing DigitalOcean encrypted Snowflake and
   Spaces credentials are reused from the live job templates. The new provider
   secrets are attached only to the temporary job, never to a persistent job.
   The production environment secret-name inventory on 2026-09-28 found all
   four absent. Recheck the names before execution; absence fails before an
   operation deploys.
   The owner can set each value interactively, without putting it on a command
   line or in a file:

   ```powershell
   gh secret set NCBI_EMAIL --repo Caraway-Labs/one-health-lyme-gap-atlas-data --env production
   gh secret set NEO4J_RUNTIME_PASSWORD --repo Caraway-Labs/one-health-lyme-gap-atlas-data --env production
   gh secret set GROQ_API_KEY --repo Caraway-Labs/one-health-lyme-gap-atlas-data --env production
   gh secret set OPENAI_API_KEY --repo Caraway-Labs/one-health-lyme-gap-atlas-data --env production
   gh secret list --repo Caraway-Labs/one-health-lyme-gap-atlas-data --env production
   ```
3. The production reviewer approves each workflow invocation. Review the
   selected family, record bound, expected eligible queue, and provider budget
   before approval. All seven workflows that update the production App spec,
   including promotion, use the shared `prod-app-topology` concurrency group
   with running jobs protected from cancellation. This prevents overlapping
   spec updates after the reconciled workflows are merged. Reviewers must
   still check for externally initiated App updates or older workflow runs;
   this workflow rejects unexpected jobs already in the app spec.

The protected workflow is
`.github/workflows/run-prod-literature-once.yml`. Each invocation must specify
the current immutable image digest:

```powershell
$prodAppId = '5d8966ed-d152-4a78-bdd6-14553dbc1483'
$digest = ((doctl apps spec get $prodAppId --format json | ConvertFrom-Json).jobs[0].image.digest)
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=preflight -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.20
```

`preflight` checks all three literature operations: required secret names (presence
only), actual runtime Snowflake role and read contract, the DATA #528 diagnostic
constraint, budget-procedure grant, Spaces bucket access, and private Neo4j Bolt
connectivity. It returns one `READY` or `BLOCKED` JSON result with all detected
blockers, affected stages, retryability, and next actions. It performs no PubMed
query, extraction, Snowflake write, or Neo4j write. After the workflow
finishes, verify that `doctl apps spec get $prodAppId --format json` lists only
the original six jobs and no `literature-*-once` job. Stop if restoration fails.

Before the workflow can change App/VPC topology, its existing spec builder emits
one sanitized host-secret report. It lists every missing required literature
secret and inherited Snowflake/Spaces credential together, mapped to discovery,
extraction or corpus stages, with owner, retryability and next action. A `preflight`
invocation checks the secret prerequisites for all three operations; other
invocations check only their selected operation. Optional `NCBI_API_KEY` absence
does not block. No credential value or captured App spec enters this report.

The report's `scope=host_secret_presence` and `runtime_readiness=NOT_CHECKED` are
explicit: `READY` here proves only secret configuration presence/protection, not
database contracts, private connectivity, artifact access or provider validity.
The existing runtime preflight still checks those accessible runtime contracts
before claim. If host readiness is `BLOCKED`, no temporary spec is written and
the workflow performs neither the App update nor its restoration update. Fix the
named configuration and repeat the protected operation; do not bypass the gate.
Reports use the existing workflow run ID and remain in its sanitized logs after
private temporary report/spec files are removed.

For a local fixture or previously authorized privately captured spec, the same
builder accepts `--readiness-report <private-json-path>` alongside its existing
arguments. Never publish the baseline or generated deployment specification.
This host check does not provide a durable pre-batch canary gate or a complete
pre-topology network/database readiness proof.

The discovery output's `discovery_run_id` is the batch key for later operations.
Supply that same UUID as the workflow's optional `discovery_run_id` input for
extraction and corpus rebuild. When supplied, the extraction claim and corpus
admission are restricted to that discovery batch. The worker appends a sanitized
attempt context and failure diagnostic to the existing Snowflake attempt ledger.
Use `atlas-data pipeline literature-status --discovery-run-id <UUID>` with an
authorized read connection to see exact PMIDs, attempt IDs, stage counts,
failure categories, retryability, provider rationale, graph receipts, and corpus
admission. The command reads only existing ledgers and receipts. Run it after
each one-paper job and after corpus rebuild; an older unscoped attempt may still
appear for a PMID that belongs to more than one historical discovery run.

## 1. Discover up to 400 citation records in one family

Choose a family from `surveillance_epidemiology`, `vector_host_pathogen`,
`environment_exposure`, or `diagnostics_interventions_outcomes`. One invocation
fetches at most 400 PubMed records, matching the existing worker bound. The
default remains 25; use a reviewed larger window only when the existing
candidate queue is too small. Keep EFetch pages at 25 records. It makes one
E-utilities ESearch plus at most `ceil(max_records/batch_size)` EFetch pages,
with at most three attempts per request and serial execution. The discovery
result contains `discovery_run_id` and artifact IDs; it creates review
candidates only.

```powershell
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=discover -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.20
gh run list --repo Caraway-Labs/one-health-lyme-gap-atlas-data --workflow run-prod-literature-once.yml --limit 5
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT DISCOVERY_RUN_ID,FAMILY,STATUS,RESULT_COUNT,NEXT_RETSTART,RAW_ARTIFACT_ID,STARTED_AT FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS ORDER BY STARTED_AT DESC LIMIT 10" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,PMCID,TITLE,STATE,ACCESS_STATUS FROM KNOWLEDGE_GRAPH.PAPERS WHERE STATE='awaiting_review' ORDER BY DISCOVERED_AT,PMID LIMIT 50" --format JSON
```

Do not rerun a successful family merely to grow the queue without checking
existing PMIDs and review decisions. Discovery is keyed by PMID and retains
query-match and raw-artifact lineage.

For DATA #495, the prior surveillance run captured only the first 10 results
from a 3,096-result query. A reviewed 400-record run of the same family can
extend that metadata-only window without changing the query, publication
types, date range, or OA policy. Compare distinct PMIDs and PMCIDs across
families before requesting further windows. Discovery does not approve or
extract any candidate; prepare the PMID, title, publication types, PMCID,
abstract, and query-match evidence for steward review below.

## 2. Steward review

The human steward inspects the specific PMIDs, title, publication type, PMCID,
and study relevance. An active steward uses the governed batch procedure with
the `ATLAS_PROD_OWNER` identity. Replace the example PMID, rationale, and
correlation ID with actual reviewed values; run separate calls for approve,
reject, or defer groups. The procedure checks the steward allowlist, paper
states, rationale length, and exact selected IDs and writes immutable decisions
and state events. A pipeline runtime cannot call it.

```powershell
snow sql -c ATLAS_PROD_OWNER -q "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()" --format JSON
$steward = 'AUTHENTICATED_USER_FROM_IDENTITY_QUERY'
snow sql -c ATLAS_PROD_OWNER -q "CALL GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(ARRAY_CONSTRUCT('REVIEWED_PMID'), 'approved', 'Reviewed full-text candidate for the bounded DATA 495 batch', '$steward', 'data-497-v1', 'DATA-495-BATCH-01')" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,DECISION,BATCH_ID,DECIDED_AT FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS ORDER BY DECIDED_AT DESC LIMIT 50" --format JSON
```

Use the effective steward username from the identity query, not the example
literal, and never approve on the operator's behalf. Approval does not imply OA
qualification; the extraction worker checks PMC identity, license, and JATS.

## 3. Extract one approved paper and publish its graph contribution

### Fractional budget bootstrap for DATA #495

Before applying V132/V133, the production owner must review the live reserve
procedure owner and grants. V132 requires the existing reserve procedure to be
owned by `OH_LYME_PROD_KG_LLM_BUDGET_OWNER`, and that role needs `INSERT` on
`GOVERNANCE.LLM_BUDGET_USAGE` in addition to its existing `SELECT`. These are
the only new persistent authority changes. The owner executes, from an
authorized administrative connection, after confirming the current grants:

```sql
GRANT INSERT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.LLM_BUDGET_USAGE
  TO ROLE OH_LYME_PROD_KG_LLM_BUDGET_OWNER;
GRANT OWNERSHIP ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR, NUMBER, NUMBER, NUMBER)
  TO ROLE OH_LYME_PROD_KG_LLM_BUDGET_OWNER COPY CURRENT GRANTS;
```

Verify ownership and that the existing `OH_LYME_PROD_RUNTIME`,
`OH_LYME_PROD_READ`, and `OH_LYME_API_READER` USAGE grants remain. Then apply
V132/V133 through the normal protected promotion. Never edit V067 or V131.
V132 preserves fractional reservation inputs and totals; V133 preserves a
fractional finalization value if one is available. The extraction worker does
not measure provider charges, so it records `NULL` actual cost rather than
putting its reservation estimate in that field.

For the approved next batch, pass `estimated_cost_usd=0.20` for each one-paper
extraction. The worker refuses a smaller reservation. Its OpenAI request is
limited to 200,000 UTF-8 bytes including the schema and 32,768 output tokens.
At published gpt-5.6-luna long-context and cache-write prices, the conservative
maximum is $0.100 input + $0.059 output; one embeddings request at the API's
300,000-token maximum adds $0.006, for under $0.165 per invocation. There is
one Responses request pinned to the standard (`default`) service tier and one
embeddings request, with no SDK retry loop.
Each attempt reserves $0.20 even on failure; reconcile reservations across
days to keep the user's additional OpenAI exposure below $30. This is a
conservative bound, not billed usage. The already completed one-paper proof
has request ID `dd0ccc75-84c8-4766-853a-9fe348e115ed` and is outside the
new batch. Before **every** subsequent extraction, use the existing
`BVB26657_PAT` administrative read connection to reconcile the append-only
ledger; routine PROD owner and audit connections cannot read this table. Require exactly
one baseline row, all new reservations at least $0.20, and `bound_usd + 0.20
<= 30`. Count failed attempts too. The shared `prod-app-topology` workflow
concurrency group serializes these one-shot runs; check no other extraction
worker is active before dispatch. Never infer spend headroom from the two
historical zeroed estimates.

```sql
USE WAREHOUSE OH_LYME_PROD_INGEST_XS_WH;
WITH baseline AS (
  SELECT RECORDED_AT FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.LLM_BUDGET_USAGE
  WHERE WORKLOAD = 'pmc_extraction'
    AND REQUEST_ID = 'dd0ccc75-84c8-4766-853a-9fe348e115ed'
), batch AS (
  SELECT ESTIMATED_COST_USD
  FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.LLM_BUDGET_USAGE
  WHERE WORKLOAD = 'pmc_extraction'
    AND RECORDED_AT > (SELECT RECORDED_AT FROM baseline)
)
SELECT (SELECT COUNT(*) FROM baseline) AS BASELINE_ROWS,
       COUNT(*) AS BATCH_ATTEMPTS,
       COALESCE(COUNT_IF(ESTIMATED_COST_USD < 0.20), 0) AS UNDER_RESERVED_ATTEMPTS,
       COALESCE(SUM(GREATEST(ESTIMATED_COST_USD, 0.20)), 0) AS BOUND_USD
FROM batch;
```

Stop if the baseline is missing, a reservation is under $0.20, the ledger is
unavailable, or the next reservation would exceed $30. Verify each new row
stores at least `0.200000` before continuing beyond the first post-repair run.

### PROD classification-ledger prerequisite (DATA #517)

The deployed worker's `claim_one` query reads
`KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS` before claiming a paper.
V060 and V064 created and extended this append-only ledger only in DEV. Before
retrying a failed PROD extraction, the protected PROD migration ledger must show
V129 applied. Confirm the PROD table has the seven DEV-equivalent columns, both
`provider_rejected_pre_inference` and `contract_remediation_reopen` classification
values, and only `SELECT, INSERT` on this table for `OH_LYME_PROD_RUNTIME`.
Run the worker's claim `SELECT` as that runtime identity after protected apply;
verify it returns the expected approved PMID without changing its paper state.
Do not retry extraction from migration syntax or grants alone. The initial
DATA #495 failure was before paper claim and left PMID `42381666` approved.

The existing `pmc-extract` command claims at most **one** approved or retryable
paper with a PMCID per workflow run. It prioritizes retry-pending work, then
orders by PMID; there is no arbitrary PMID override. Review the eligible queue
before each invocation. Do not run simultaneous extraction invocations. The
worker performs PMC OAI-PMH JATS retrieval, OA/license/identity checks,
immutable artifact handling, one budget-reserved model extraction, embedding,
validated Neo4j publication, and an append-only graph receipt. There is no
separate direct Neo4j write command.

```powershell
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,PMCID,STATE,FINAL_REVIEW_DECISION_ID FROM KNOWLEDGE_GRAPH.PAPERS WHERE STATE IN ('approved','retry_pending') AND PMCID IS NOT NULL ORDER BY CASE WHEN STATE='retry_pending' THEN 0 ELSE 1 END,PMID LIMIT 25" --format JSON
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=extract -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.20 -f discovery_run_id=$discoveryRunId
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,STATE,ACCESS_STATUS,FULL_TEXT_OBJECT_KEY,CONTENT_SHA256 FROM KNOWLEDGE_GRAPH.PAPERS WHERE STATE IN ('processed','retry_pending','retry_exhausted','access_rejected') ORDER BY UPDATED_AT DESC LIMIT 25" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,PMCID,ARTIFACT_ID,LICENSE_URL,JATS_SHA256,TEXT_SHA256 FROM KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS ORDER BY ADMITTED_AT DESC LIMIT 25" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,ATTEMPT_NUMBER,PROVIDER_ROUTE,STATUS,ERROR_CLASS,STARTED_AT,FINISHED_AT FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS ORDER BY STARTED_AT DESC LIMIT 25" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,GRAPH_RECEIPT_ID,CONTRIBUTION_SHA256,NEO4J_TRANSACTION_ID,PASSAGE_COUNT,PUBLISHED_AT FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS ORDER BY PUBLISHED_AT DESC LIMIT 25" --format JSON
```

The job output returns the processed PMID and graph receipt identifiers. For a
10–25-paper group, invoke and reconcile one paper at a time. One failed paper
does not require rediscovery. Follow the append-only recovery controls for
provider rejection; never rewrite extraction attempts or force a retry state.

The worker's budget procedure has existing limits of **$20 per day and $300
per month** for reserved/used extraction estimates. `estimated_cost_usd` is an
operator-supplied reservation estimate, not a measured provider charge or a
reliable pricing quote. The CLI enforces `0.01 < value <= 20`; the workflow
requires 0.01–20. The worker routes one complete request to Groq if the
conservative input estimate fits, otherwise to OpenAI, and may request one
OpenAI embedding batch. Confirm remaining budget and provider quota externally
before scaling beyond the first bounded group. A single invocation can claim
one paper, make one PMC request, one model request, and one embedding request;
failed-provider retries occur in later explicit invocations and only confirmed
LLM executions count toward the three-failure ceiling.

## 4. Rebuild the derived retrieval corpus

After reconciling the graph receipts for the group, trigger one corpus rebuild.
This processes all eligible production papers; it does not replace the Neo4j
serving gate. The build requires processed state, review decision, matching
immutable JATS/text hashes, and a graph contribution receipt. It records a
versioned build ID and content hash.

```powershell
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=build-corpus -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.20 -f discovery_run_id=$discoveryRunId
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT BUILD_ID,CORPUS_RULES_VERSION,STATUS,PAPERS_ADMITTED,CHUNKS_WRITTEN,CORPUS_CONTENT_SHA256,STARTED_AT FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS ORDER BY STARTED_AT DESC LIMIT 5" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,PMCID,COUNT(*) AS UNITS FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS WHERE CORPUS_RULES_VERSION='retrieval-corpus-v1' GROUP BY PMID,PMCID ORDER BY PMID" --format JSON
```

Production Neo4j article/passage counts and fixed-template Assistant retrieval
must be verified separately through the approved private graph and API paths
before DATA #495 claims serving readiness. Snowflake receipts alone do not
prove live graph content. Record the before/after counts and representative
PMIDs in DATA #495; full answer QA remains KG #13.

## Deployment and recovery

The workflow pins the image to the digest active in both DEV and PROD, checks
the exact six scheduled jobs, clones only their encrypted production runtime
credentials into one temporary job, and refuses missing operation secrets.
Deployment success means that the selected pre-deploy command exited zero.
Its exit trap restores the captured baseline spec. Verify the six jobs and
active digest after every run. If restoration fails, stop all further app
deployments and have the production owner restore the retained baseline or
previous approved deployment revision using the normal protected path. Keep
Snowflake artifacts, attempts, and graph receipts intact; do not reset them.

## Bounded literature trace export

The literature CLI buffers up to 128 finished child spans for up to five minutes.
When the command ends, it queues the finished CLI root before its children and
then flushes the standard SDK batch exporter. This gives a tail sampler the final
root error status at its first decision, rather than only an early successful
preflight span. Failed PMC stages and blocked preflight spans carry ERROR status
with a bounded category; exception bodies are not recorded.

The SDK queue and export batch are capped at 256 spans; each span has at most
64 attributes with strings capped at 1,024 characters, and no events or links.
Full existing sanitized diagnostics remain in the durable ledgers. Flush and
shutdown each wait at most five seconds for their delegate calls, up to ten
seconds combined. Lock acquisition and child draining precede those waits;
the installed production batch processor queues spans without blocking. These
limits do not provide a universal bound for arbitrary custom delegates.
The current OTLP endpoint and opaque headers are reused without collector,
sampling, credential, grant, or persistent-job changes.
Parsed headers are validated before exporter construction; malformed headers
disable optional tracing with a fixed safe diagnostic and ingestion continues.
The SDK's two diagnostics that include raw transport/HTTP reasons retain safe
HTTP status, retry delay, and finite reason categories; raw reasons and exception
details are removed before logging handlers receive them. Other SDK diagnostics
remain enabled, and connection retries retain their SDK behavior.

This processor supports one literature CLI invocation per worker process.
Concurrent or reentrant CLI invocations in one Python process are unsupported:
the root state and provider shutdown belong to that invocation. Concurrent
child spans within the single invocation are supported; each separate worker
process has its own processor and provider.

A span limit, five-minute deferral expiry, early explicit flush, or shutdown
switches to normal streaming and emits a safe `atlas-data.trace_buffer` warning.
The time limit bounds buffering, not execution: it does not terminate a command
or alter budgets, retries, or governance. After fallback, complete-trace/error
retention is not promised. SIGKILL, hard termination, or a process crash can lose
buffered spans; already committed attempt context and diagnostics still survive.
Graceful Python exceptions and exits close the root before the CLI flush boundary.

When an actual OTel context exists, `trace_id` is stored in the existing
`attempt_context` and `stage_failure` JSON diagnostics and returned by bounded
literature status inspection. A missing/invalid context does not invent an ID.
This permits direct collector lookup after temporary worker cleanup. A stored ID
or completed SDK flush is not evidence that a collector retained the trace.
The current pilot samples successful traces at 10%; late spans can inherit an
earlier discard decision. Validate a received trace's source, digest, workflow,
run, and attempt identity separately before declaring end-to-end delivery.

## KG15 group gate implementation boundary

The [group gate contract](kg15-group-gate.md) documents the first offline-reviewed
inventory/claim seam. The protected workflow does not expose its manifest yet.
Group continuation is explicitly blocked until authoritative same-group fresh
canary receipts, corpus admission and actual serving visibility are implemented.
Existing one-paper invocations and final batch counts do not complete this gate.
No production canary, new access or workflow activation is authorized by this seam.
