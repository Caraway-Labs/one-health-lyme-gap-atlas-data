# CDC consumer batch v1

Owner: Data engineering and scientific stewardship. Related: API #248,
ADR 0045; existing CDC admission/metadata and ADRs 0042–0044 remain authoritative.
This is an internal Python producer contract, not an HTTP or publication contract.

## Interface and connection ownership

```python
from lyme_gap_atlas_data.cdc_consumer_batch import produce_cdc_batch_v1

result = produce_cdc_batch_v1(
    query,
    "scapularis_status",
    ("01001", "13081"),
    environment="prod",
    release_id="governed-2026-10-15-january-climate-prod",
)
# CDCBatchResultV1: contract_version, measure_id, release_id,
# county_fips tuple, observations tuple in exactly the requested order.
```

`query: Callable[[str, tuple[str, ...]], list[dict[str, Any]]]` executes bound SQL
and returns up to two rows, preserving native VARIANT objects or JSON strings.
It borrows the caller's exclusive request-owned connection. It must not log SQL
parameters, authority, private record keys or raw driver exceptions. The producer
opens/closes no connection, changes no session setting, and caches nothing across
requests. The caller retains timeout, cancellation, cursor and connection cleanup.
The existing singleton functions, defaults, output and SQL remain unchanged.

Inputs: one supported CDC measure, one explicitly packaged reviewed release,
environment dev/prod and 1–50 distinct ASCII five-digit county strings in a
sequence. Invalid input fails before SQL. A batch cannot mix measures/releases.
The bound is internal; it does not expand any API request/pagination limits.

Output: frozen `CDCBatchResultV1` dataclass with contract version
`atlas-cdc-consumer-batch-v1` and complete consumer-safe observations. Nested
observation dictionaries are ordinary owned output dictionaries, not an immutable
cache. No private SQL authority is included. Serialization to HTTP, endpoint
behavior and pagination remain API-owned and require separately approved work.

## Scientific and security invariants

Each request validates exact intended-reader role/database plus nonempty user
and warehouse. One authority SELECT from the existing secure
`LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V` returns all facts and shared proof in
one statement snapshot. No base relation, new view, DDL, grant or persisted
projection is introduced. Record-level admission is never cached or preapproved.

SQL filters exact release, measure, source version and parameterized FIPS. It
retains up to TWO rows per county so duplicate evidence cannot disappear under
a global limit. Shared full review decisions and receipts are returned once;
SQL requires their exact equality for every retained row, with NULL comparisons
treated as false. Equality is deliberately fail closed, including order changes
in arrays; it does not normalize or reinterpret review conditions.

Python requires exactly one envelope, exact closed envelope/row fields, true
shared consistency, one row for every requested county, no extra county or
duplicate observation ID, and exact release/bundle/measure/source tuple. It
rejects row-level proof shadowing and malformed shared proof. The envelope has
an 8 MiB UTF-8 JSON safety ceiling; exceeding it fails closed, with no fallback.
This is a post-fetch validation bound, not a guarantee of connector peak memory
or underlying physical scan work. At most 100 slim county rows enter the envelope.

The complete shared proof is reconstructed into each exact row in memory.
Every row runs unchanged `_inputs`, `map_record` and
`project_surveillance_evidence`; all rows must succeed before any result returns.
This retains immutable metadata validation, exact physical/semantic membership,
source approval and retirement, evidence/derivation/artifact/hash identity,
active unsuperseded human decisions, genuine receipts and unchanged donor proof.
No count-only admission or caller-provided membership replaces retained review.

Both `scapularis_status` and `burgdorferi_status` retain cumulative 2025-12-31,
publisher values, NO_RECORDS -> unknown, method and limitations. October 15
bundle `53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d`
uses packaged revision 3 and exact source versions. October 6 binding/revision 2
and genuine donor receipts remain unchanged; no automatic historical fallback.
Source tuples, metadata identities and reviewed bindings remain defined in
`cdc_consumer_admission.py` and packaged `cdc-2025` resources. Excluded,
unsupported, missing, duplicate or unauthorized evidence fails the entire batch;
no fabricated absence, risk claim, partial success or omitted county is returned.
The existing pre-publication compatibility gate is unchanged.

Public entry-point errors are fixed `CDCConsumerUnavailable` messages without
private diagnostics. Cancellation (`BaseException`) propagates so the owner can
unwind resources. Internal projection errors are not public diagnostic APIs.

## Operation counts and evidence

For 1/2/5/10/50 processed counties, authority SELECT count is **1/1/1/1/1**;
identity count is one. With the API's existing two setup statements and one
release lookup, a future integration would execute five explicit statements for
each batch, versus current 5/7/13/23/103. SDK implicit statements are additional.
This Data PR changes no API behavior. Pagination lookahead is a processed county
and may require a separately bounded call if it crosses the internal limit.

Repeated compilation and shared-proof transport are reduced structurally;
latency must be measured. A single statement may still expand the complex secure
view and compile slowly. No result-cache, cold/warm, warehouse or SLO claim follows
from query counts. Synthetic tests prove behavior under test authority, not live
admission; read-only benchmark evidence must identify environment, exact source,
query IDs, timing/cache limitations and payload units independently.

## Acceptance, integration and rollback

Tests cover exact singleton equality for both measures, current/historical
bindings, 1/2/5/10/50 counties, caller ordering, privacy, malformed inputs and
envelopes, duplicate/missing/extra records, invalid second-county authority,
read-role rejection, envelope ceiling, safe driver failure and cancellation.
SQL snapshot/equality/cardinality must also be checked with bounded reader SQL;
Python fixture tests do not execute Snowflake SQL.

Data quality, typing, packaging, dbt parse and container gates precede release.
After human review/merge, an API change may pin the reviewed immutable Data
commit, borrow its request connection and retain existing filters, order,
pagination/lookahead, errors and public schemas. That integration and protected
production deployment require separate authorization. Rollback is the prior
approved API/Data pin using the unchanged singleton seam; no data/receipt/review
rewrites or release-pointer changes. Do not merge/deploy this PR automatically.
