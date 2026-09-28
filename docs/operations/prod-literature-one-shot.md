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
   The repository has no evidence that those four provider secrets are
   provisioned today; absence fails before an operation deploys.
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
   before approval. Only one invocation runs at a time through workflow
   concurrency. Run no other production app topology workflow concurrently;
   this workflow rejects any unexpected job already in the app spec.

The protected workflow is
`.github/workflows/run-prod-literature-once.yml`. Each invocation must specify
the current immutable image digest:

```powershell
$prodAppId = '5d8966ed-d152-4a78-bdd6-14553dbc1483'
$digest = ((doctl apps spec get $prodAppId --format json | ConvertFrom-Json).jobs[0].image.digest)
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=preflight -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.10
```

`preflight` checks private Neo4j Bolt connectivity inside the temporary VPC job.
It performs no PubMed query, extraction, Snowflake write, or Neo4j write. After the workflow
finishes, verify that `doctl apps spec get $prodAppId --format json` lists only
the original six jobs and no `literature-*-once` job. Stop if restoration fails.

## 1. Discover at most 10–25 citations in one family

Choose a family from `surveillance_epidemiology`, `vector_host_pathogen`,
`environment_exposure`, or `diagnostics_interventions_outcomes`. One invocation
per family fetches at most 25 PubMed records. The worker permits at most 400
records in general, but this workflow narrows the limit to 25. It makes one
E-utilities ESearch plus at most `ceil(max_records/batch_size)` EFetch pages,
with at most three attempts per request and serial execution. The discovery
result contains `discovery_run_id` and artifact IDs; it creates review
candidates only.

```powershell
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=discover -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.10
gh run list --repo Caraway-Labs/one-health-lyme-gap-atlas-data --workflow run-prod-literature-once.yml --limit 5
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT DISCOVERY_RUN_ID,FAMILY,STATUS,RESULT_COUNT,NEXT_RETSTART,RAW_ARTIFACT_ID,STARTED_AT FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS ORDER BY STARTED_AT DESC LIMIT 10" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,PMCID,TITLE,STATE,ACCESS_STATUS FROM KNOWLEDGE_GRAPH.PAPERS WHERE STATE='awaiting_review' ORDER BY DISCOVERED_AT,PMID LIMIT 50" --format JSON
```

Do not rerun a successful family merely to grow the queue without checking
existing PMIDs and review decisions. Discovery is keyed by PMID and retains
query-match and raw-artifact lineage.

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
snow sql -c ATLAS_PROD_OWNER -q "CALL GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(ARRAY_CONSTRUCT('REVIEWED_PMID'), 'approved', 'Reviewed full-text candidate for the bounded DATA 495 batch', 'MATTHEWCARAWAY', 'data-497-v1', 'DATA-495-BATCH-01')" --format JSON
snow sql -c ATLAS_PROD_RUNTIME_AUDIT -q "SELECT PMID,DECISION,BATCH_ID,DECIDED_AT FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS ORDER BY DECIDED_AT DESC LIMIT 50" --format JSON
```

Use the effective steward username from the identity query, not the example
literal, and never approve on the operator's behalf. Approval does not imply OA
qualification; the extraction worker checks PMC identity, license, and JATS.

## 3. Extract one approved paper and publish its graph contribution

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
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=extract -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.10
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
gh workflow run run-prod-literature-once.yml --repo Caraway-Labs/one-health-lyme-gap-atlas-data --ref main -f image_digest=$digest -f operation=build-corpus -f family=surveillance_epidemiology -f max_records=25 -f batch_size=25 -f estimated_cost_usd=0.10
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
