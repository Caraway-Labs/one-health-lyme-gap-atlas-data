# EID Expedited DEV admission proposal

Status: review proposal only; no live requests, source activation, registry writes,
grants, migrations or workflow dispatch. Baseline main:
`b9d64bb49a776afa8fa899eddbba13da1ae52666`.

## Authority and evidence

[Matthew's October 3 selection](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/132#issuecomment-5964095143)
approves RSS Candidates rows 2–9, once daily. EID Expedited is row 6.
NIAID, WHO and CDC Vital Signs (rows 10–12) are deferred. This supersedes
the preliminary all-11 interpretation and the later stale five-source/Vital
Signs-first pilot assertion. The committed feed-selection-v1.json already
represents eight approved and three deferred sources; preserve that decision.
The decision record was created at 2026-10-03T01:26:35Z; this is the comment
timestamp, not an exact timestamp of Matthew's human approval.

[Retention decision](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/132#issuecomment-5964564895):
raw copies expire after 30 days; eligible normalized metadata/provenance remains
long term subject to source permissions. No 90-day metadata deletion. Duration
approval does not establish source rights or physical expiry enforcement.

`tests/fixtures/intelligence/native-captures/cdc-eid-expedited.json` records
HTTP 200 at 2026-10-03T03:06:52.954325Z, 1564 bytes, 2 items and 16 observed
paths; transport SHA256:
`d5157794b405c94455703d42bf580bcf46a1b6c4d1f9801d49bbbf3b1a414366`.
One sanitized sample covers all observed paths. Raw transport was not retained.
These are historical qualification facts, not current availability or DEV
ingestion. Existing real-feed metadata tests cover mapping, missingness and
unexpected-path rejection. The fixture's registry_version=1 and source checksum
are fixture facts, not an allocated live registry version/checksum.

[CDC reuse terms](https://www.cdc.gov/other/agencymaterials.html), reviewed by
the delegated assistant on October 7, permit much agency material with exceptions
for third-party, contractor, grantee and other protected work. Conservative
proposal: agency attribution, original canonical links, title and publisher
chronology only; no descriptions, article text, image values/bytes, logos or
inferred geography/topics. Preserve substance, identify free originals and
nonendorsement. These restrictions require consumer treatment before publication;
this proposal does not implement WEB work or grant blanket reuse rights.

## Minimal implementation delta for review

1. Add `config/sources/intelligence_cdc_eid_expedited.yml` using the existing NIH
   SourceDefinition shape: source/resource `cdc-eid-expedited`, rss_atom, exact
   `https://wwwnc.cdc.gov/eid/rss/expedited.xml`, publisher_document_order,
   CONTENT_REVISION, publication/no inferred geography, publisher chronology with
   missing unknown, PRESENTATION.INTELLIGENCE_FEED_V2, daily,
   REVIEW_REQUIRED, maximum_rows=250. Definition version is configuration version,
   not a claim about a live registry record.
2. Replace deferred Vital Signs in the existing runtime ENDPOINTS map and
   acquisition-only workflow definition guard with EID Expedited. Keep NIH;
   admit no deferred feed. Update actual guard/compose regression cases rather
   than create another workflow, adapter or orchestration entry point.
3. Keep `config/intelligence/pilot-policy-receipts.json` empty until real registry
   facts and independent review resolve the receipt below. Do not insert a
   placeholder into executable receipts. Existing compose_pilot performs latest
   registry version/checksum checks and uses existing retention, checkpoints,
   stage effects and the bounded adapter.
4. Add only the reviewed receipt once its missing fields are genuine. Do not
   alter source schemas to permit a fabricated timestamp, version or approval.

## Receipt fields and unresolved prerequisites

| Existing field | Evidence-backed proposal / missing fact |
|---|---|
| source_id | cdc-eid-expedited |
| decision_ref | Independently reviewed technical admission reference; cite October 3 product decision separately |
| registry_version | UNKNOWN until actual latest registry state is read and next version reviewed |
| source_sha256 | UNKNOWN until exact complete source record is reviewed; recompute using identity_hash |
| retention_policy_ref | Reviewed source-specific eligible-metadata policy reference, still missing |
| raw_policy_ref | intelligence-raw-30d-v1, conditional on verified actual source binding and operational storage enforcement |
| artifact_policy | Existing reviewed restricted feed artifact policy identifier, still missing; never inherit PUBLIC_SEVEN_YEAR |
| native_policy.policy_ref | Reviewed EID Expedited technical mapping reference, still missing |
| native_policy.source_sha256 | Same UNKNOWN real source checksum, not fixture checksum |
| native_policy.inventory | Exact 16 observed fixture paths; retain counts and historical capture date separately |
| native_policy.permitted_paths | feed/language, feed/link, feed/title, item/link, item/pubDate, item/title only |
| native_policy.published_path / format | item/pubDate / rfc822, evidenced historically |
| native_policy.updated_path / format | null / iso8601 default; updated absent, never inferred from fetch time |
| native_policy.required_paths | [] initially; do not invent required publisher fields |

The complete source record also needs exact endpoint/host, daily poll_seconds=86400,
expected_item_seconds=null, no inferred topics/geographies, bounds of 2MiB/30s/
250 items/zero redirects/one attempt, actual trust classification and accurately
attributed technical trust/approval review. Historical availability_verified_at
can truthfully cite the October 3 capture, but is not a fresh availability claim.
The fixture's inherited tick-borne topic is not native evidence and must be removed.

ADR 0027 and AGENTS.md permit routine Tier B technical checks without a human
steward click solely to advance stages. A delegated assistant may author a
technical review with its actual current review time and an accurately named
delegated reviewer, citing existing product/retention decisions. It must not sign
as Matthew or intelligence-steward. Runtime never approves. Independent code
review and existing authorized owner registration remain necessary; genuine
licensing ambiguity or broader retained/public content routes to Tier D named
human review. No new general source-selection approval is required here.

## Next sequence

Independently review this exact conservative scope and the narrow admission diff;
obtain actual bounded registry/warehouse evidence through the parent-coordinated
authorized path; finalize/review exact source document and checksum; coordinate
existing minimal DEV DDL/grants and registration slot; then review the executable
receipt and one acquisition-only invocation. Physical raw deletion remains a
separate held obligation before the 30-day expiry, not delivered by this proposal.
Do not dispatch until all execution guards pass.

This proposal consumes no live HTTP attempts. Warehouse and execution accounting
remain in private operational records, not an instruction to execute. First
capture would be durable ACQUIRE only; normalization/load, idempotent repoll and
reader proof remain additional DATA #135 acceptance work. DATA #132 still needs
three approved feeds and truthful status of all relevant candidates.
