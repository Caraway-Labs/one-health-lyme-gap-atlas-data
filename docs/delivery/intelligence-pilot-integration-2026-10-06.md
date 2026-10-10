# Approved five-source pilot integration preparation

This October 6 five-source pilot snapshot does not govern the later, separately
approved EID Expedited first DEV acquisition. PR #637 retains the Vital Signs
route for this pilot and adds EID for that later decision; neither route can run
without its own reviewed source registration and policy receipt.

DATA #132/#135 baseline: origin/main `819dde4` on October 6, 2026.
Owner: desktop Lane B, branch `codex/data132-dev-integration-20261006`,
worktree `data-132`. API #84 has a separate owner. API #179 is closed
NOT_PLANNED and is outside this work. No WEB or ML-chain changes.

The overnight instruction and current #132 acceptance replace the earlier
eight-source selection for this pilot. Use
`config/intelligence/feed-pilot-2026-10-06.json`, an instance of the existing
`intelligence-selection-v1` contract, with `prepare_daily_sources`.
The October 3 selection remains historical evidence and must not be passed
to this pilot. WHO Newsroom is distinct from WHO disease-outbreak news.
No MMWR, EID, PubMed, article retrieval or other source belongs to this run.
Selection does not load the private registry, authorize raw retention, enable
the default adapter, or schedule execution.

## Existing implementation and genuine remaining acceptance

#535/#536 and V135 provide shared RSS/Atom acquisition, normalization, immutable
revisions/captures and acquisition receipts. #581 preserves native/derived
metadata; #583/#589 enforce original-capture raw expiry; #590 provides durable
health outcomes. These components are reused, not rebuilt. The default
`rss_atom` adapter rejects live acquisition, and ordinary live orchestrator
effects select scientific `SnowflakeStageEffects`; a pilot must explicitly
inject the existing `IntelligenceFeedAdapter`, `IntelligenceStageEffects`,
compatible intelligence checkpoints and the same `FeedRawRetention` controller.
Do not route publications into scientific observations or weaken the defaults.

Real DEV run/repoll, intended-role readback, legitimate revision attribution,
and consumer native/derived provenance remain unproved for this five-source
pilot. Historical deployment and ledger receipts do not prove current source
registry authority or reader access. V135 is already merged; no new competing
schema is proposed. Unnumbered v2 SQL review files are proposals, not evidence
that their objects exist. Current effective role, migration ledger, registry
versions/rights, object access and public projection must be inspected before
any execution. Runtime must not populate or approve the registry.

## Endpoint and fixture status

| Source | Endpoint evidence | Fixture/mapping status | Remaining gate |
| --- | --- | --- | --- |
| CDC Online Newsroom | Existing genuine October 3 capture pins media/132608.rss | Two bounded native metadata samples and reviewed mapping candidate already committed; 1,844 items observed in historical full feed | Fresh availability, current immutable approved registry/mapping/retention and DEV integration |
| NIH News Releases | Official [news-release page](https://www.nih.gov/news-events/news-releases) links news-releases/feed.xml; October 6 browser fetch reported RSS content type, not parsed XML | No genuine accepted fixture yet; historical desktop 403 is not a new success/failure claim | Bounded actual adapter capture and verified mapping |
| NIAID News | Official news-events page returned 403 to browser research October 6 | BLOCKED: exact publisher feed endpoint and genuine fixture not established | Publisher endpoint evidence; no guessed URL or denial bypass |
| CDC Vital Signs | Official [digital-media page](https://www.cdc.gov/vitalsigns/digitalmedia.html) links media/275866.rss; browser fetch reported XML content type | Endpoint documented; genuine native inventory/fixture/mapping not captured here | Bounded actual adapter capture and verified mapping |
| WHO Newsroom | Parent-coordinated endpoint research verified https://www.who.int/rss-feeds/news-english.xml: HTTP 200, RSS 2.0, 25 items, 140,955 bytes | STALE/INCOMPLETE: newest item February 25, 2026 despite October newsroom updates; accepted native fixture/mapping still outstanding | Excluded from first DEV pass; explicit stale/incomplete health/coverage limitation and source-specific rights required before integration; no outbreak substitute |

Availability research is not accepted ingestion. No raw XML was persisted or
source run executed in this preparation. WHO's [copyright guidance](https://www.who.int/about/policies/publishing/copyright)
distinguishes licences, third-party content and commercial-use permissions;
it does not establish an Atlas raw-retention or excerpt grant.
WHO's October 5 HTTP Last-Modified is transport metadata, not publisher item
freshness. The snapshot now records its verified endpoint; source approval and
endpoint resolution do not make it eligible for current-coverage claims.
Do not run every snapshot entry merely because preparation finds registry
authority: the initial execution scope is CDC Vital Signs, then NIH if eligible.
The parent-coordinated researcher owns the WHO raw endpoint capture evidence;
this work has neither copied that XML nor claimed a successful DEV ingestion.

## Proposed DEV execution bound, awaiting permission/budget verification

Existing infrastructure only. First inspect named DEV identity/warehouse,
V135 and relevant runtime objects, immutable approved source versions and
intended reader permissions using bounded metadata queries. Then one first
capture and one repoll per eligible source: at most ten feed requests overall,
no article requests, at most 5 MB and 5,000 items per capture, 30 seconds per
request, no unbounded retry/backfill. Source-specific reviewed limits must be
at least as restrictive. No source may silently truncate oversized input.
Serialized warehouse writes retain the existing 5-second lock and 120-second
statement bounds. Keep raw expiry at 30 days from original successful capture;
no cleanup or new lifecycle is part of the run. Excerpts/full text remain off
unless separate source-specific rights establish permission.

Before paid Snowflake or source execution, confirm an existing approval or
explicit spend cap for this lane; NLCD's budget is unrelated. Existing source
permission does not prove budget or effective runtime privileges. Unknown or
denied authority blocks dependent actions; no credentials/grants/security or
infrastructure changes are authorized by this preparation.

For each accepted source, retain run/artifact SHA, immutable registry checksum,
parser/fetch version, fetched time, publisher raw/normalized dates, native
inventory and derived-method provenance. Repoll must retain unchanged item
identity/revision without duplicate items while capturing the new run. Saved
run replay must avoid another fetch/write. A quiet successful poll must remain
distinct from failure. Verify legitimate revisions with controlled fixtures;
do not edit live publisher content or fabricate a live correction. Read the
existing consumer projection with its intended reader and check that no XML,
private locators or raw publisher identity escapes. Require three approved
feeds with accepted real DEV evidence for #132, one for #135, plus their other
criteria. Keep both issues open until scoped acceptance and review are real.
