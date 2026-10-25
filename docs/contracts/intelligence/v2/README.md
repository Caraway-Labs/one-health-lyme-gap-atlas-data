# Intelligence item v2 — native metadata extension

DATA #578 follows the delivered #131 v1 contract and open #132/#135. Source and
health contracts remain v1; item records opt into `2.0.0` only through a trusted
source/version `NativeMetadataPolicy` lookup. The adapter and writer independently
resolve that policy. A source definition or capture cannot approve retention.
No runtime composition, source activation, scheduler, migration or grant is applied.

The existing canonical fields remain, with `publisher_metadata` for publisher,
source family, readable source item ID, authors, unrestricted-category strings,
language, optional public media references, date states, and an optional
sanitized plain-text publisher description. The description is present only when
the reviewed receipt permits that path. Its text is complete plain text with
state `present`, `empty`, or `not_provided`. Publisher category
strings remain separate from reviewed taxonomy tokens. Images are references
only; no image or article fetch occurs. `derived_metadata` is strictly empty.
There is no model call, relevance score, urgency claim or inferred disease/geography.

Private `native_metadata` retains a bounded ordered structured tree with expanded
namespace names, attributes, repeated fields, meaningful mixed-content tails,
observed inventory, explicit value states and reviewed policy identity/checksum.
Permitted metadata values are sanitized plain text; raw markup, descriptions and
article content are not implicitly approved. Denied values remain null/withheld,
with their observed field shape retained. Oversized fields/collections/metadata
fail instead of truncating native evidence. Unknown paths or missing required
paths fail parser drift checks. Source policy changes require a new reviewed
snapshot; inventory is not copying permission.

Publisher dates additionally retain their exact bounded raw string, normalized UTC
value, explicit invalid/not-provided state and selected dialect in private data.
Profiles select RSS RFC 822, namespaced ISO 8601, or the NIH Drupal wall-clock
dialect below. A missing zone on RFC 822 or ISO 8601 stays invalid. Retrieval
time never supplies missing publisher chronology. No event date is invented.
Exact fractional UTC precision remains preserved.

## NIH news-release publication time

`nih-news-releases` may select `published_format` `nih_drupal_wallclock` together
with `published_timezone` `America/New_York`. That pair is valid only for this
source. The item `pubDate` text is a weekday and `MM/DD/YYYY - HH:MM` with no
zone. The reader strips surrounding whitespace, requires the weekday to match
the calendar date, and converts that America/New_York wall clock to canonical
UTC. `America/New_York` is the IANA zone for US Eastern, including its
daylight-saving transitions. An ambiguous local time, including the repeated
fall-back hour, and a local time that does not exist, including the
spring-forward gap, stay invalid with a null normalized value. The stored raw
publisher string is the original text.

On 2026-10-25 the owner decided to read NIH item publish times as US Eastern,
and only for NIH. The Eastern basis is the recorded feed channel `pubDate`
offset `-0400`, which is the same instant as the newest item's `13:00` wall
clock, and NIH's location in Bethesda, Maryland. The applied NIH receipt
remains `rfc822`.

`config/intelligence/nih-news-releases-settings-receipt-prepared.json` is the
prepared settings receipt. It is not applied. Runtime loading stays on the
applied receipts.

Revision content includes eligible publisher/native metadata, so GUID attributes,
categories, language, author/media and chronology-format changes are not dropped
when URL/title/date otherwise match. Canonical article identity stays stable;
multiple native variants within or across feeds retain distinct revisions and
source attribution. Exact duplicates still replay. Fetch/run/provenance and
derived enrichment, feed refresh timestamps and policy-receipt identity are outside publisher content identity. Feed metadata remains in each private capture. Existing private
VARIANT captures retain the complete v2 objects, and revisions retain item-native content under the same
atomic writer guard. V1 identities and records remain supported.

Five genuine CDC metadata captures provide observed full-feed inventories and
bounded actual samples covering all observed paths: MMWR32paths/3samples,
EIDAhead16/1, EIDExpedited16/1, Outbreaks19/1, Newsroom38/2. They are structured
JSON metadata fixtures, not persisted raw transport XML. Tests reconstruct
rights-sanitized XML in memory and verify source mapping and drift; withheld
original text is neither reconstructed nor claimed tested. The real feeds also
exposed a sanitizer buffering defect for CDC `&c=` links; closing the HTML parser
preserves that text without allowing markup. Fixture capture endpoints/times,
HTTP200, transport SHA/bytes and actual item counts are recorded. Candidate source
and mapping receipts remain explicitly pending; fixtures do not prove accepted
ingestion, intended-role writes, rights approval, or full feed completeness.

PubMed's two generated RSS endpoints remain unresolved and NIH returned403 on
normal transport. No synthetic substitution is provided for these three approved
sources; per-source real fixture acceptance remains open. No denied-access bypass.

[CDC reuse guidance](https://www.cdc.gov/other/agencymaterials.html) requires
attribution/no endorsement and identifies third-party exceptions. Source material
is available free via canonical CDC links. Capture scope retains metadata facts
and references, withholding descriptions/full text and image bytes. These fixtures
are not a blanket live rights receipt for native text or media reuse.

`presentation-projection.sql` is a review template, not a reserved migration.
It preserves existing v1 view grants and restricts that view to v1 records, while
adding a version-filtered v2 view with explicit canonical publisher fields and
empty derived metadata. Private native objects/raw dates/XML/policy receipts are
absent. API #172 consumes the stable projection, never publisher XML. Reserve the
shared migration slot and verify actual API reader roles before execution.
API #90/#44 continue their strict v1 briefing/digest contracts; v2 artifact
delivery needs its own compatibility change, not a silent v1 relabel.

Approved retention remains long-term eligible normalized metadata/provenance,
30days raw copies and separate UI recency/archive display. **Raw expiry is not
implemented by this extension.** DATA #135 must cover all raw XML objects,
`xml_base64` in `INGESTION_RUN_PAYLOADS`/local stores, cached/replay copies and
resume paths. A304 or retry must not renew an old capture. Scoped cleanup/audit,
cache invalidation, immutable capture deadlines and restart/expiry tests remain
mandatory before feed deployment. No90daymetadata deletion.

## PROD operational deadline safeguard (DATA #680)

The October 20 owner retention decision permits standard Snowflake platform
Time Travel/Fail-safe recovery. Active Snowflake checkpoint and Spaces RSS raw
copies must be removed no later than successful capture + 30 days. For the
fixed PROD EID pilot, proactive cleanup and raw I/O cutoff occur 48 hours before
that immutable maximum; DEV and other-source policy boundaries are unchanged.
The same cutoff gates raw read/write, replay, checkpoint resave and conditional
reuse, preventing a cleaned copy from being recreated under an old lease.
V162 is a separately reviewed forward migration; historical leases and V150 are
not rewritten. This correction grants no execution or source activation.
[Operational cadence/failure acceptance](../../../operations/intelligence-proactive-cleanup-prod.md)
requires intended-role physical proof and separately approved daily execution.
