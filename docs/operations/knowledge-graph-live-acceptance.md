# Knowledge-Graph Live Acceptance

Run this protected checklist after CI succeeds and before enabling public
evidence chat. It implements the live-acceptance condition in ADR 0007; a
green unit-test run is not permission to enable the feature flag.

1. Apply migrations through `V032` to the intended governed DEV or PROD
   database with the checksum-validated migration command. Confirm that the
   pipeline role has the narrow `V030` grants and the API role has only the
   owner-rights chat procedures.
2. Provision the private Neo4j runtime, apply `001_graph_schema.cypher`, and
   install the protected shared `graph_runtime` credential only in the API and
   pipeline runtime stores. Verify that Bolt is VPC-only and Browser/HTTP is
   unpublished.
3. Configure the `pubmed-discovery-*` and `approved-paper-extraction` jobs
   from `.do/app.prod.yaml`, including encrypted NCBI, Spaces, Neo4j, Groq,
   and OpenAI values. Do not print or export their values.
4. Run one bounded PubMed family in DEV. Confirm its EFetch XML checksum and
   object key, normalized paper/query-match records, and the steward review
   queue. Record the run ID and selected PMID.
5. As a steward, approve a permitted PMCID paper. Run one extraction worker
   and reconcile the PMC artifact ledger, paper content hash/object key,
   extraction receipt, Neo4j transaction ID, passage count, and PubMed link.
6. Create a Neo4j backup, perform the prescribed restore test, and retain its
   checksum, graph counts, and fixed-retrieval evidence.
7. Exercise the disabled API endpoint, evidence-unavailable path, no-evidence
   path, safety refusal, capability-token history path, rate limit, and a
   grounded answer with citations. Attach the results and rollback plan to the
   release record.
8. Obtain the recorded owner sign-off. Only then set both server and public
   feature flags for the approved deployment. Rollback is flag-first; retain
   artifacts, ledgers, and graph state.
