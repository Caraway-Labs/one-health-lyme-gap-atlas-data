# Intelligence raw retention implementation boundary

Matthew's October 3 decision retains eligible normalized metadata/provenance
long term and raw feed copies for 30 days. Excerpts/full article text require
separate rights. The old 7/90/365 proposal is superseded. Neither metadata nor
publisher dates are silently deleted/refreshed by this policy.

`intelligence_retention.py` is an inactive, feed-only control library. It has no
CLI, scheduled task, warehouse DDL, credentials, object deletion adapter, or
default approval. It is **not complete enforcement of DATA #135**.

The private authoritative ledger must create an immutable successful-200 capture
lease and source/version/rights binding. Raw copies reference the lease hash.
A 304, retry, resume, checkpoint resave or cache-reference change reuses that
lease; it cannot mint a new capture. A genuinely fresh 200 may create a distinct
lease even if bytes are identical. Readers reject at `now >= expires_at`, before
loading bytes or decoding base64. Expired validators are discarded and a normal
fresh request is required, never an accepted 304 with unavailable retained bytes.

Every copy needs a claim before its write, including `feed.xml` objects, embedded
Snowflake `GOVERNANCE.INGESTION_RUN_PAYLOADS` XML, local checkpoint JSON, process
payloads, conditional caches, binary replay, and artifact members. Immutable
claim metadata must be readable independently of XML. Normalized item/revision/
capture provenance tables are outside cleanup scope. A live claim protects a
shared physical object, but cannot authorize reading an expired original lease.

Cleanup plans contain an exact environment, source allowlist, private locators,
immutable lease references, and inventory checksum. The trusted approval callback
must approve that exact plan hash. No real cleanup has been approved or executed.
Inventory/claims, reads, write registration, and deletion must use the same ledger
lock/transaction; otherwise a fresh claim could race an object deletion. Cleanup
callbacks are idempotent. Durable pending intent precedes physical deletion;
success/failure follows it. Receipts contain hashes/outcomes, no XML, private
locator, or provider exception. Audit failure stops further mutations.

Still required before activation:

- Implement/review the private durable lease/claim/audit schema and intended
  roles with the parent; reserve a migration number and shared deployment slot.
- Bind the authoritative capture authority to actual successful fetch receipts;
  do not let a payload or source YAML issue leases or reset their timestamps.
- Register and guard **all** copy paths above, including checkpoint reads before
  loading VARIANT/XML and every orchestrator resume fallback; add actual restart
  integration tests. The current library's fake ledger tests are not that proof.
- Supply scoped concrete purge adapters for checkpoint payload removal, local
  copies, caches, objects and replay members while retaining structured metadata,
  hashes, source context and append-only audit. No scientific lifecycle changes.
- Validate inventory completeness, serialization/races, crash-after-delete
  recovery and intended-role DEV readback; review an exact cleanup plan before
  any irreversible real deletion. Deploy/schedule only with parent coordination.

Supported official access was rechecked October 3 at 03:59 UTC using normal pinned
TLS, no proxy/authentication/access-denial bypass. NIH's exact approved
`https://www.nih.gov/news-releases/feed.xml` returned HTTP403. A bounded public
PubMed search also returned HTTP403; neither approved search's generated RSS URL
is resolved. NIH's official news page still links the exact approved endpoint:
<https://www.nih.gov/news-events/news-releases>. PubMed documents generated RSS
via its public search UI and a maximum 200-item feed window:
<https://pubmed.ncbi.nlm.nih.gov/help/#create-an-rss-feed-for-a-search>.
No replacement endpoint, fabricated fixture, subscription or source activation
was introduced.
