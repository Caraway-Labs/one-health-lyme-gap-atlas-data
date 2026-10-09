# Protected frozen membership inspection

The existing canonical pilot `inspect` action succeeded on reviewed main in run
37095612795: 389856 revisions and normalized rows, 1560 completed partitions,
and exact retained NOAA/Census artifact hashes. This is actual runtime visibility,
separate from unavailable local read/owner visibility. No new grant or credential
is required to use that existing service route.

`nclimgrid-pilot-measure --action frozen-membership` adds the remaining bounded
read to the same canonical `run-ingestion.yml` workflow. It requires reviewed main
and successful exact-head quality, DEV/Tier B, the fixed definition/run, and false
recapture/publication flags. The actual existing runtime identity is checked
before all SELECTs. The wrapper accepts no other run or local output fallback.

It validates the completed run and both retained hashes/sizes, reads the current
PUBLISHED ATLAS release and its five-source annual manifest, and freezes the
sorted selected capture IDs and five-tuple membership digest used by publication.
The result is capped at the fixed January count plus one rejection row. Extra,
missing, unordered or malformed rows and pointer movement fail atomically without
replacing an existing artifact. No warehouse object or provenance row is written.

The complete selected ID list and five-field tuples remain in the existing
`GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS` table for the fixed run. V103
grants the DEV runtime `SELECT`/`INSERT` and the migration deployer `SELECT`;
the ingestion path only inserts unmatched captures. The annual manifest remains
in the published `PRESENTATION.SEMANTIC_RELEASES.source_manifest` row. The
protected same-job diagnostic emits a compact proof of the release/bundle,
source-manifest digest, exact row count, tuple digest and artifact digest, then
deletes the job-local copies. It does not expose the full ID list or manifest in
logs or a public repository artifact. Its status is explicitly
READ_ONLY_CANDIDATE_NOT_PUBLICATION. The proof does not approve a source,
publish a release or prove PROD parity.

After independent review/merge and main quality, dispatch the existing protected
DEV `deploy-dev.yml` same-job January pair on the actual reviewed main commit.
Before preparing the release manifest, re-read the complete sorted capture IDs
from the fixed run/source/artifact predicates with
`climate_release.reconstruct_capture_ids`; its five-field digest and exact total
count must equal the protected run proof. Re-read the annual manifest by the
recorded donor release ID and bundle hash, and verify its canonical digest.
The logged `annual_manifest_sha256` is SHA-256 of UTF-8 `jq -S -c
'.annual_manifest'` output, including its final newline; use the same sorted,
compact serialization when comparing the Snowflake readback.
The 389,856 IDs must be placed in the release extension; a digest alone is not
the published membership. Additional or changed source rows fail reconstruction.
The complete manifest still requires independent review, the actual technical
review record, target payload/storage checks and protected publication. This is
no additional Matthew product-acceptance question.
