# DEV retrieval corpus rebuild

Rebuilds the versioned Research Assistant chunk corpus from steward-processed
PMC Open Access artifacts. This is a derived projection, not immutable
extraction-attempt evidence.

## Eligibility

A paper enters the corpus only when all are true:

- `KNOWLEDGE_GRAPH.PAPERS.state = processed`
- `final_review_decision_id` is present
- `PMC_FULL_TEXT_ARTIFACTS` row exists with matching JATS/text hashes
- `GRAPH_PUBLICATION_RECEIPTS.contribution_sha256` exists

Unapproved, rejected, deferred, retrying, or incomplete papers are counted in
`papers_excluded_unapproved` and never written as units.

## Command

```powershell
uv run atlas-data pipeline build-retrieval-corpus --confirm
uv run atlas-data pipeline build-retrieval-corpus --confirm --pmid 42472018
```

DEV only (`TOPX_ENV=dev`). Requires pipeline Snowflake credentials and Spaces
read access to admitted JATS object keys.

## Verification queries

```sql
SELECT * FROM GOVERNANCE.V_RETRIEVAL_CORPUS_BUILD_METRICS
ORDER BY started_at DESC LIMIT 5;

SELECT pmid, pmcid, chunk_index, section_label, unit_text_sha256,
       artifact_id, contribution_sha256, object_key
FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS
WHERE corpus_rules_version = 'retrieval-corpus-v1'
ORDER BY pmid, chunk_index
LIMIT 20;
```

Rebuild the same inputs and confirm `corpus_content_sha256` matches the prior
completed build for `retrieval-corpus-v1`.

## Out of scope

- Re-enabling the PMC extraction timer
- PROD promotion
- Rewriting extraction attempt history
