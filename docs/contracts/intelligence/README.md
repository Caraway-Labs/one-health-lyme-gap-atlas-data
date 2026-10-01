# Intelligence ingestion contract v1

Owner: DATA repository. Review state: proposed for independent parent review.
Story: #131; consumer handoff: API #90/#44/#45. WEB #66 is context only.

This contract describes publication-level intelligence, not measured disease
occurrence. An article mentioning a county is not a county observation, and an
empty feed is not evidence of low disease risk. The existing county semantic
model and its released API are unaffected.

## Acceptance and implementation plan

| #131 acceptance | Artifact / observable evidence |
|---|---|
| Source identity, organization, family, scope, trust, transport, cadence, state, rights, review | `v1/source.schema.json`, candidate registry fixture, activation rejection tests |
| Fetch/item timing, versions, failures, quiet versus broken | `v1/health.schema.json`, quiet and failure fixtures, negative state tests |
| Normalized items, chronology, provenance, identity, revisions, missingness | `v1/item.schema.json`, transport examples and rejection tests |
| Publisher versus inference; untrusted input | Typed tag origin/method/version/confidence; plain-text fields; injection fixture |
| Source-family onboarding with actual availability/rights verification | `source-onboarding.md`; no production source activated |
| Common consumer contract; private-payload exclusion | Four transport fixtures pass the same schema; unknown private fields rejected |

Only schemas, fixtures, tests, and documentation belong to #131. #132 supplies
bounded adapters; #135 owns persistence and consumer projections; #136 owns
reviewed operational thresholds. This plan implements the user's explicit
authorization to start #131 and preserves the approved dependency order.

## Versioning and source activation

The three JSON Schema Draft 2020-12 documents under `v1/` are authoritative for
DATA adapter outputs. `contract_version=1.0.0` is required. Validate with format
checking enabled; schema validation alone does not grant source rights or network
authority. `$id` values are identifiers, not hosted endpoints. Breaking changes
require a new major contract and consumer review. Registry versions are immutable
positive integers per source; changes require a new reviewed version.

Candidate entries are disabled. Active/manual entries require a reviewed trust
classification and explicit approval reference, verified availability, terms,
retention reference, and locations/allowlist. Approval references must resolve to
actual recorded decisions, never to fixture strings. Runtime identities cannot
approve a source. This supplements existing Tier A/B/C/D policy and does not
broaden approval authority. Trust labels are reviewed categories, not numerical
ranking or alert eligibility decisions.

Registry scope tags describe the source portfolio, not every item. Empty item
tags mean no supported relevance metadata. Neither source scope nor an author's
affiliation may automatically become item geography.

Email `fetch_location` remains null: dedicated provider/mailbox configuration and
sender mappings live in private server-side configuration, referenced by source
ID. Never put mailbox addresses, auth tokens, recipient lists, raw headers,
provider message IDs, tracking links, or private subscription URLs in these
public-safe documents. Email approval does not authorize attachments or linked
page acquisition. Web approval must name the exact page and justify why RSS/email
is unavailable; an approved host is not permission to crawl every page.

## Item identity and revision semantics

All identity digests use SHA-256 over UTF-8 canonical JSON: sorted object keys,
compact separators, no ASCII escaping, no NaN. Version the normalization rules
as `intelligence-identity-v1` in provenance.

Before hashing publisher/update/event timestamps, canonicalize their strict UTC
RFC3339 representation to `YYYY-MM-DDTHH:MM:SS[.fraction]Z`: replace `+00:00`
with `Z`, remove trailing fractional zeroes, and omit the fraction if zero.
Preserve all remaining fractional digits; never round or truncate them.
For example, `2026-09-29T08:00:00.100+00:00` becomes
`2026-09-29T08:00:00.1Z`. Equivalent UTC spellings must not create revisions.
Compact ISO dates/times are not accepted; calendar validation is mandatory.
This timestamp subset does not support leap-second `:60` values; retain their
unsupported chronology limitation instead of silently rewriting them.

1. Canonical URL: HTTPS only; no userinfo, fragment, secret/query tracking fields,
   or nonstandard port. Lowercase host and remove port 443. Preserve path case,
   trailing slash, percent encodings, and semantically significant query fields.
   Removing a query key requires source-specific reviewed rules. Never fetch an
   item link merely to canonicalize it. Malformed/unsafe URLs become null with
   state `invalid`; unknown canonical URLs stay unknown.
2. `deduplication_key = H({"canonical_url": canonical_url})` when a safe URL is
   available. Otherwise use H({"source_id": source_id,
   "transport_identity_sha256": transport_identity_sha256}). Without either
   reliable publisher identity or URL, use the permitted content digest as the
   transport identity and record that content-only identity cannot reliably link
   future corrections. Never equate different URLs from title similarity alone.
3. `item_id = deduplication_key`. The same canonical article across sources can
   share an item ID; persist each source/transport attribution separately.
4. `content_sha256 = H({"title": title, "excerpt": excerpt,
   "published_at": published_at, "updated_at": updated_at, "event_at": event_at})`.
   `revision_id = H({"item_id": item_id, "content_sha256": content_sha256})`.
   Retain conflicting publisher metadata as distinct attributed revisions; do
   not overwrite an earlier capture or infer a winner from arrival time.
5. Transport identity is H of the publisher GUID/Atom ID or approved web-page
   identity. For email, hash a privately normalized message identifier before
   projection; use a scoped keyed digest when low-entropy private identifiers
   could be guessed. No raw mailbox/provider identity leaves private storage.

Fetched time, run/artifact IDs, tags, and transport are excluded from content
revision identity. Repolling identical content creates a new capture attribution,
not a new revision. Tag changes require versioned enrichment evidence, not a
fabricated publisher correction. This rule does not resolve syndication with
different canonical URLs; #135 must record that limitation instead of using
unreviewed fuzzy merging.

## Chronology, missingness, and text

Every optional publisher field has a required state: `present`, `not_provided`,
`withheld`, or `invalid`. Only `present` permits a non-null value. Missing dates
must never be replaced by retrieval time. UTC timestamps include timezone;
date-only publisher values remain unknown in this timestamp contract unless a
source-reviewed precision rule exists, with the limitation retained. Event time
is separate and appears only when actually supported. Future publication dates
are possible; do not silently clip them. Item-observed time is operational fetch
time of the latest accepted capture, not a substitute publication date.

Excerpts and titles are plain text, never HTML or executable instructions. #132
must decode entities, remove unsafe markup/control characters, enforce the
source's permitted excerpt length and rights, and validate the result. A
`public_excerpt_permitted=false` source must emit null/`withheld` excerpt.
An excerpt is source-provided text, not an invented summary. Inferred tags need
method and method version, plus confidence when available; null confidence means
unquantified, never certainty. No inference engine or summarizer is introduced.
Consumers must render text as text and must never use embedded instructions to
expand tools, network access, or source authority.

## Cross-record validations required before writes

Adapters/storage must check the item source ID and immutable registry version,
transport, known run/artifact/checksum references, excerpt permission/length,
canonical URL policy, and approval decision against the registry. Enforce source
fetch locations and redirects with host and network destination checks; schema
URI syntax is not SSRF protection. Hash and chronology invariants must be checked
in executable adapter/storage code. The contract fixtures are synthetic, not
approval receipts, real fetch evidence, or deployed storage evidence.

Reuse `create_artifact`, immutable run/checkpoint evidence, redacted diagnostics,
and existing source-policy patterns where compatible. Store private artifact
locations only internally. The public item projection exposes opaque artifact
and run references/checksums, not object keys or payloads. #135 needs additive
forward-only storage at article/revision/attribution grain; never send these
items through county-observation loaders or grant broad RAW access.

## Health semantics and consumer handoff

`healthy` means a successful fetch/parse/persist with accepted items; `quiet`
means successful validation with zero new accepted items (including HTTP 304
after a prior successful parse). Neither implies recent publication. A 304
without a valid prior capture cannot prove healthy extraction. Fetch success is
updated only by verified fetch outcomes, and item observed only by accepted
items. Coverage bounds describe the actual bounded capture window, not global
publisher coverage. `stale` requires a reviewed policy threshold; unknown cadence
must not become stale automatically. Paused/manual controls suppress scheduled
work without deleting last valid items.

Parser drift, access expiry, rate limits, upstream outage, malformed content,
partial acceptance/persistence, and telemetry failure remain distinct. Failure
diagnostics are allowlisted codes, never raw exception text or message content.
Quiet and healthy outcomes have no rejected items; a healthy capture has at
least one accepted item and a last-item-observed timestamp. Parser drift/malformed
states require a parser failure and a positive consecutive-failure count;
rate-limit/upstream-outage states require a fetch failure and positive count;
access expiry requires fetch/policy failure and positive count. Partial outcomes
require parser/policy/storage failure with positive count, plus rejected items
unless the failure is persistence itself. Stale outcomes require a reviewed
policy reference. These are record invariants, not source threshold decisions.
`never_fetched` has no successful fetch/item timestamps, accepted/rejected items,
or failure evidence; failed attempts use their explicit failure state instead.
Retries remain within source limits and transient-failure policy. #136 must add
reviewed thresholds, owners, escalation, alert deduplication, recovery, and real
runtime evidence; no monitoring platform or notification delivery is added here.

API #90 can consume the same item shape regardless of transport. It must retain
the source ID/version, distinct timestamps/states, attribution/provenance,
tag origin, and limitations. Source organization/trust/cadence are looked up
from that immutable registry version. Public endpoints, OpenAPI, ranking,
subscriber preferences, digest idempotency, and alert rules belong to API. No WEB
implementation or REST compatibility change is included. Digest generation is
periodic intelligence, never an official public-health alert.

## Remaining gates

| Story | Gate / release evidence still required |
|---|---|
| #132 | Contract review; three source-specific verified endpoints/rights/approval records and approved bounded schedule; actual repoll evidence |
| #133 | Dedicated provider/mailbox, owner approval and subscription allowlist; no personal inbox use or subscriptions initiated |
| #134 | Exact approved pages/hosts, fallback reasons and site-access policy |
| #135 | Reviewed storage/retention policy, intended-role DEV proof and parent-coordinated migrations/promotion |
| #136 | Source-specific reviewed operational thresholds/owner and delivered-channel evidence |
| API #90 | Owning API contract review and OpenAPI/fixture tests |
| API #44 | Subscriber preference dependency and delivery/provider authorization; no emails sent |
| API #45 | Product-approved eligibility/materiality/confidence/cooldown rules |

DATA production rollout is reserved for parent coordination with #495/#528.
This contract has no migrations, grants, jobs, deployments, external subscriptions,
credentials, or spending changes. Rollback is to omit these proposed schemas from
consumer adoption; existing released contracts remain available.
