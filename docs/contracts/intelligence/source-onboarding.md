# Source-family onboarding decisions

Review date: 2026-10-01. This is an onboarding checklist, not an approved feed
registry. Availability and rights are independent requirements. Endpoint
verification must be repeated at activation and evidence retained with the
source version. No active feeds or schedules are created by #131.

| Family | Decision and evidence required before activation |
|---|---|
| CDC/MMWR | Discover the actual feed from the current publisher page. The attempted historical `cdc.gov/mmwr/rss.html` documentation URL returned 404 during this review; do not assume it is a valid feed. Capture the current endpoint, redirects, cadence, and applicable publication/third-party rights before activation. |
| CDC/EID | The later EID Expedited selection pins `https://wwwnc.cdc.gov/eid/rss/expedited.xml`; the October 3 bounded metadata capture returned HTTP 200 with two items (`tests/fixtures/intelligence/native-captures/cdc-eid-expedited.json`). This establishes historical endpoint availability, not live source registration or reuse rights. Before activation, review issue/article identity, updates, attribution, third-party exceptions, metadata-only publication, and the exact source/retention/native-policy receipts. |
| NIH/NIAID | Verify a relevant news/research feed on the current publisher site; grant/podcast feeds are not evidence that a NIAID disease-news feed exists. [NIAID reuse guidance](https://www.niaid.nih.gov/global/copyright-and-reuse) is a review starting point, not blanket permission for linked third-party articles. The page could not be read in this review; rights remain unverified. |
| PubMed | The [current PubMed help page](https://pubmed.ncbi.nlm.nih.gov/help/#rss-feeds) documents RSS creation for a search. Save the owner-approved exact Lyme/tick-borne query, generated feed URL, result bound, and change review policy. A generated search feed is not the existing EFetch/PMC pipeline. Review citation/abstract reuse terms independently; abstracts/full text are not automatically public domain. No query/feed was generated or activated here. |
| State/local | No jurisdiction or endpoint is selected. For each selected department, identify the official publisher and actual feed/subscription. Record geography semantics and rights; lack of RSS does not automatically authorize email or web scraping. |

For each candidate: retain dated publisher documentation, exact transport URL,
bounded read-only availability evidence, access/terms review, content allowance
and retention/deletion policy, escalation owner, cadence evidence, and actual
approval reference. Set `state=candidate` while anything is unresolved. A review
request or synthetic fixture is not an approval. Reverify changed endpoints,
rights, parser assumptions, and cadence using a new source version.

Use RSS/Atom first. Dedicated subscribed email requires the separate #133 owner
decision. Web fallback requires #134's exact page approval and documented reason
preferred transports are unavailable. Neither an email link nor a web hyperlink
expands acquisition authority. Credentials and mailbox identities remain private.
