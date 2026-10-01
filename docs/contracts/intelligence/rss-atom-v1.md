# RSS/Atom implementation and activation gates

DATA #132 owns `intelligence_items.py` and `ingestion/intelligence_feed.py`.
DATA #135 is stacked on #132 and consumes this implementation without a second
normalizer. Review/merge #132 first, then reconcile #135 with current main;
neither PR authorizes production release.

Private retained payloads now require `source_context` version
`intelligence-acquisition-v1`: source ID, immutable registry version/checksum,
requested/effective HTTPS URLs, fetch status/time, capture mode and raw-byte SHA.
`resource_key` must equal registry `source_id`; no implicit source mapping exists.
Replay and conditional cache validation reject missing context or registry,
rights, endpoint and identity drift even when the XML bytes are unchanged.
Fixture captures are explicitly marked `fixture` and cannot authorize live
warehouse retention. The public #131 item/source/health schemas stay unchanged.
DATA #135 must record and check the immutable run/artifact context receipt before
inserting normalized captures. Atom URL resolution uses the verified effective
response URL and inherited root/entry/link `xml:base`; unsupported bases fail
closed. Invalid RFC3339 offset components remain invalid chronology. Unmapped
distinct publisher categories produce one counted limitation, retaining raw
publisher text only in the private artifact.

The `rss_atom` adapter uses the existing source definition, artifact/run capture,
checkpoint/resume and stage state machine. Tier A may read bounded `sample.xml`
fixtures for a candidate source. No source definition or schedule is activated.
The default adapter rejects all live acquisition. A future reviewed composition
must inject an authoritative, checksummed registry lookup and a permission check
that resolves the source's actual retention policy and permits raw feed replay.
Setting approval fields in source YAML cannot enable the default live adapter.
The approved feed endpoint must match the source definition exactly.

Live acquisition uses HTTPS with verified TLS/SNI, a pinned public IP from a
bounded DNS lookup, no environment proxy, no automatic redirects and no article
fetches. Every resolved address and redirect host must be permitted. Redirects
are bounded separately from transient-response attempts. Only 429 and 5xx receive
bounded backoff; long/date Retry-After values defer the poll rather than shorten
the publisher's requested wait. Authentication and parser errors are not retried.
Source limits bound bytes, elapsed time, redirects, attempts and items; XML DTDs,
entities, deep trees and excessive nodes are rejected, including UTF-16 DTDs.
Compressed responses are rejected; requests ask for identity encoding.

A conditional poll requires a validated retained `FeedCache` tied to the exact
registry checksum and private artifact ID. An injected retained-cache permission
check must verify the actual prior artifact reference and body checksum; merely
constructing a `FeedCache` does not authorize it. Safe response validators remain
in the private replay manifest and are never public item fields or log values.
Validators never pass to a redirected
endpoint. A 304 without that capture fails closed. Existing capture bytes are
registered in the new run, preserving their SHA and the new fetch/run provenance.
Cache creation/retrieval and approved scheduler composition remain activation
work: no in-memory cache is represented as durable production evidence.

RSS 2.0 and namespaced Atom 1.0 are supported. GUID/Atom IDs are hashed rather
than exposed. Canonical article URLs define cross-feed identity; unchanged
content retains its revision even when publisher IDs change, while publisher
corrections and conflicting chronology remain distinct revisions. A missing ID
and URL falls back to source-scoped content identity with an explicit limitation.
Missing publisher dates stay unknown; malformed/date-only values stay invalid.
Fetch dates come from the saved acquisition manifest and are never substituted
for publisher dates. Bare XML cannot resume without its manifest. Source topic
tokens remain publisher supplied, geography/event dates remain unknown, and no
inference or summary is performed. Markup is reduced to permitted plain text;
embedded instructions remain untrusted data.

Tests simulate CDC/MMWR, NIH/NIAID and PubMed family shapes using synthetic
candidate records and `example.org` XML. They do not establish feed availability,
source permission or live success for those organizations. Actual approved
endpoints, trust/rights/retention review, bounded schedule, durable conditional
cache, three-family live run/repoll evidence, #135 intended-role storage and #136
health publication are outstanding acceptance gates. Successful empty feeds have
an explicit quiet outcome; failures have redacted codes and cannot become quiet.
The generic county-observation Snowflake effects reject this adapter.
