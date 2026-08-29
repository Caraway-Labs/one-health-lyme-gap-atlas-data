# one-health-lyme-gap-atlas-data

The repository contains two deliberately separate capabilities:

- **Alpha POC loader:** idempotent provisioning/loading for the current exact
  release; it continues to support the existing API and is not migrated.
- **Governed pipeline:** catalog discovery, source approval, immutable
  artifacts, provenance, source-faithful RAW loading, and dbt through
  `CONFORMED` in `ONE_HEALTH_LYME_GAP_ATLAS_DEV`.

The governed pipeline contract is in `docs/contracts/catalog-to-snowflake/`.
See workspace ADR 0005 before provisioning it.
Deployment and DEV-to-PROD promotion are governed by workspace ADR 0006 and
the [deployment runbook](docs/operations/deployment-promotion.md).

The knowledge-graph pipeline uses the protected `graph_runtime` Neo4j
Community identity described in the knowledge-graph repository's ADR 0008.
Community does not enforce separate API-reader and pipeline-writer permissions;
the VPC, secret store, fixed API retrieval templates, and review gate are the
required compensating controls.

```powershell
uv sync --extra dev
uv run atlas-data provision --dry-run
uv run atlas-data load --release alpha-2026-08-06 --dry-run
uv run pytest
uv run atlas-data pipeline preflight
```

`pipeline preflight` is non-mutating: it checks the private Spaces bucket,
makes one metadata request per enabled catalog capability, and verifies the
dedicated pipeline service account's isolated DEV context. It does not crawl a
catalog, ingest data, or expose credentials.

The scheduled `pipeline discover` job runs the versioned catalog terms and
catalog-specific refinements against Data.gov, HealthData.gov, and Socrata/ODN.
It follows each catalog's configured cursor or offset pagination and stores
each response as a private, content-addressed artifact with append-only
Snowflake request/run lineage. It discovers metadata only; full source
ingestion remains blocked pending a steward decision.

After a discovery configuration reaches one durable `COMPLETED` run, run
`pipeline register-discovery --config-sha256 <checksum>` as a separate,
reviewed metadata-only step. Each invocation claims up to 100 immutable
artifacts and processes at most 10,000 datasets as one bounded, set-based
Snowflake transaction. It commits the corresponding durable artifact offsets
only after all dataset, resource, and observation writes succeed, and reports
`PARTIAL` until a later invocation completes the chain. Re-running it resumes
from the durable artifact-registration ledger; it does not rerun discovery.
It reads only the captured private artifacts,
normalizes catalog datasets/resources, preserves every term/catalog observation,
and publishes `GOVERNANCE.V_DISCOVERY_CANDIDATES` for triage. It does not follow
publisher URLs, retrieve samples, create access profiles or assessments, queue
an approval decision, or ingest any source payload.

### Temporary registration backfill

When a completed discovery chain has a large metadata-registration backlog,
the protected production promotion workflow deploys three bounded
`catalog-registration-01` through `catalog-registration-03` scheduled jobs.
Each runs hourly on a distinct fifteen-minute start interval (15, 30, and 45),
claims disjoint artifact leases in Snowflake, and processes at most 12 artifacts
and 1,500 datasets. This produces at most 864 artifact slots per day while
preserving the same immutable-artifact,
checkpoint, and steward-approval boundaries. The backfill is metadata-only;
it does not acquire source data, approve candidates, or run dbt.

For the first reference source, run `uv run atlas-data pipeline cdc-sample` to
capture only CDC/Socrata `x5j9-wybp` metadata and an explicitly ordered sample.
It creates a `PENDING_REVIEW` candidate in the internal Snowflake
`GOVERNANCE.SOURCE_APPROVAL_CONSOLE`; it never acquires the full dataset. The
steward's immutable decision in that console is the prerequisite for a later
full-ingestion command and dbt run.

After the quality workflow verifies a `main` commit, it builds an immutable
image and deploys that digest to DEV. Production promotion is a separate,
protected, manual GitHub workflow: it requires the configured production
reviewer and reuses the exact digest already running in DEV. It cannot create
production infrastructure or substitute the Alpha POC database. See the
[deployment runbook](docs/operations/deployment-promotion.md) for the required
production provisioning and promotion sequence.

To provision the protected PROD runtime without placing secrets in a file, use
the interactive helper from a user-controlled terminal after creating the
private `one-health-lyme-gap-atlas-data-prod` Spaces bucket and a scoped Spaces
key. It validates the bucket and the Snowflake service identity before creating
the non-routable App Platform job:

```powershell
$prodDigest = ((doctl apps spec get b33dbae7-e243-4e27-b3ca-1018f5897f87 --format json | ConvertFrom-Json).jobs[0].image.digest)
uv run python scripts/provision_prod_runtime.py --image-digest $prodDigest --confirm
```
