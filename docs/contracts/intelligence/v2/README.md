# Intelligence item v2 — native metadata extension

DATA #578 follows the delivered #131 v1 contract and open #132/#135. Source and
health contracts remain v1; item records opt into `2.0.0` only through a trusted
source/version `NativeMetadataPolicy` lookup. The adapter and writer independently
resolve that policy. A source definition or capture cannot approve retention.
No runtime composition, source activation, scheduler, migration or grant is applied.

The existing canonical fields remain, with `publisher_metadata` for publisher,
source family, readable source item ID, authors, unrestricted-category strings,
language, optional public media references and date states. Publisher category
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
Profiles explicitly map RSS RFC822 or namespaced ISO8601/Atom fields. Missing
timezone is invalid; retrieval time never supplies missing publisher chronology.
No event date is invented. Exact fractional UTC precision remains preserved.

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
