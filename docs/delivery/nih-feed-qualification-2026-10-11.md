# NIH exact-feed qualification — DATA #132

The already selected endpoint `https://www.nih.gov/news-releases/feed.xml`
returned HTTP 200 on normal desktop HTTPS transport on 2026-10-11 at
06:18:34 UTC, with `application/rss+xml; charset=utf-8`, 7,670 bytes and ten
RSS items. The later metadata fixture capture at 06:20:00 UTC had the same
transport SHA256 `a96c787bfc4b92b8cb583a98fc228847244639d2b6573d6a8ce4bf12e2658642`.
This is current availability evidence; the historical October 3 HTTP 403
receipt remains intact and neither proves permanent provider failure.

Authority checked: `config/intelligence/feed-selection-v1.json` selects NIH
as approved at this exact endpoint. Its committed SourceDefinition still has
`artifact_policy: REVIEW_REQUIRED`; `pilot-policy-receipts.json` has no NIH
source-specific retention/native-policy admission. Selection is not permission
to register, retain raw copies, ingest or activate it. Deferred sources remain
deferred. No policy receipt, rights decision or registry row was fabricated.

Three GETs total used Python requests 2.34.2's default user agent, normal TLS,
one attempt per invocation, no redirect, five-second connect and fifteen-second
read timeouts, and a two-million-byte/twenty-second body-reading ceiling.
No credentials, cookies, alternate endpoint, article request or access bypass
was supplied. The intermediate successful capture encountered an unsupported
publisher date while calculating an expectation; it wrote no fixture and
performed no warehouse work. The final capture retains just two bounded
title/link/GUID/raw-date samples. Raw XML, descriptions, article text, images
and response headers other than content type are not retained.

For an independent availability-only repro, use one normal GET with those
timeouts, `allow_redirects=False`, `stream=True`, and user agent
`python-requests/2.34.2`; inspect status/content type without saving the body.
Do not vary user agents, add cookies, follow alternate endpoints or retry a
denied response. A later result is a separate dated observation.

NIH currently supplies dates such as `Fri, 10/09/2026 - 09:30` without a
timezone. Existing parsing/normalization keeps these as invalid publisher
chronology and exposes `published_at=null`, distinct from the known fetch
timestamp. The source-specific tests reconstruct only the retained metadata;
they preserve title/link, unknown date, withheld excerpt, provenance and
deterministic revision identity. They do not claim full native-field inventory
qualification, description parsing, acquisition/storage or V2 mapping approval.

Next: obtain the existing source-specific retention/native mapping review,
qualify the full bounded field inventory without retaining unapproved text,
then use the existing governed DEV path for accepted capture/repoll/readback.
No new source admission is proposed here. Snowflake spend is zero.
