# January 2025 publication review boundary

Status: proposed; not publication approval. DATA #443 / #496, API #84.

## Verified readiness

| Capability | DEV evidence | PROD / product acceptance | Owner / next dependency |
| --- | --- | --- | --- |
| January source-backed daily climate | PR #549 merged `fffeaf24fe9746b319cc37f85d45c6a57023e1eb`; protected run [36931053172](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/36931053172) succeeded | Candidate only; no approved consumer publication | DATA #443 under #189 |
| Candidate integrity | Two complete exports, 389,856 rows each, identical digest below; no writes | Does not establish target-environment retained capture or reader access | DATA publication owner |
| Climate semantic metadata | Historical v1 remains pending, methodology `/1` | Corrected `/2` normalization needs an explicit meaning/version decision | #190–195 stewardship |
| Public daily climate API | API #84 implementation owner active | Public climate request returned 404 in the #496 audit; no named approved daily projection | API #84 after DATA contract lands |
| Existing annual county release | Fixed 3,144 counties / 14 observations per county | V127/V128 expose three annual human measures; they do not accept daily climate | Preserve existing release contract |
| Literature capture | PROD audit: 100 papers, 222 passages, 4,018 units, lineage checked | Capture is available; paid inference and retrieval audit are separate capabilities | Existing literature owners |

The full January run contains 321,313 COMPLETE/OBSERVED, 64,203 COMPLETE/ZERO,
and 4,340 OUT_OF_SOURCE_COVERAGE/UNAVAILABLE records. PARTIAL_COVERAGE and
SOURCE_MISSING behavior is fixture-tested, not observed in this live month.
Closed DATA #198 establishes completed code, not climate consumer availability.
Snowflake error 002003 means absent **or inaccessible**; it does not prove PROD
is empty. Current PROD topology and feed release remain owned by tasks
`01a0f0b0` and `01a0f5c6`; coordinate before any deployment.

## Immutable publication pins

Candidate contract: `atlas-nclimgrid-county-day-candidate-v1`.
Candidate SHA256:
`1e6b9809a5266d7cb3b4851f861835fdfddcf0d4f136a02d14e7e436806f5618`.
Selected DEV run: `c2eb2146-005d-44d2-bac4-e2805ca42577`;
resource `noaa_nclimgrid_daily_202501`, definition version 2.
NOAA retained SHA256:
`809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31`.
TIGER retained SHA256:
`9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763`.
Normalization `atlas-nclimgrid-county-day/2`; weights
`atlas-grid-county-area-weight/1`; January 1–31, 2025; four measures only.

Publication must pin actual approved NOAA and TIGER source-version IDs and
artifact IDs from authoritative joins. These IDs are not guessed here. Source
approval, immutable revision membership and target-environment capture proof
remain required even when these content hashes match. Reuse #192 source
mappings and #193 lineage validators; a digest is not an authorization substitute.

## Proposed exact implementation diff

1. Extend `semantic_release.py` with an optional, strictly validated
   `climate_extension` in the existing release manifest. Keep the five current
   source slots and 44,016 existing observations unchanged. The extension holds
   January period, four reviewed measure definitions and metadata revision IDs,
   candidate digest, selected capture revision membership, and approved
   NOAA/TIGER source-version/artifact tuples. It is included in the existing
   bundle digest and persisted in the immutable release `source_manifest`.
   Reject unknown extension fields, unreviewed metadata, incomplete membership,
   cross-run artifacts and failed source gates before inserting a release.
2. Add a separately named release-pinned daily projection,
   `PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V`, plus
   `PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V`. Resolve only the ATLAS
   pointer's PUBLISHED release and that release's verified extension membership;
   read the retained V103 revisions. No latest-run selector, new pointer,
   parallel observation store, or insertion into the fixed annual table.
   Releases without the extension expose no climate rows. Reserve the next
   migration number with the deployment owner; V136 is not reserved by this doc.
3. Register only `atlas-nclimgrid-county-day/2` in the #191 metadata method and
   #193 evidence-basis maps. Permit CONSUMER_SAFE only for the exact four
   reviewed climate definitions, January period, approved source identities and
   source-backed replay evidence. PUBLIC remains blocked. Merely setting
   REVIEWED must not unlock arbitrary derived measures. Existing tick, coverage
   and priority exposure blocks remain enforced.
4. Use existing `publish-semantic-release.yml` build/publish/rollback with an
   exact reviewed main commit, protected environment and approved release
   manifest. Publish changes the established ATLAS release pointer. Rollback
   restores the retained prior release and thereby removes daily exposure when
   that prior release has no extension. Do not independently publish a climate
   release through the current fixed-shape builder.

These are proposed changes for review, not landed implementation. The manifest
extension must be deliberate because ADR 0035 is proposed and the current
release builder does not validate such an extension today. Review this storage
boundary before coding executable publication or access DDL.

## Consumer columns and scientific meaning

API reads only release ID, measure ID, reviewed semantic version, county FIPS,
period start/end, DAY resolution, value, value state, unit, null denominator,
coverage status, source-time presence, expected/intersected/source-supported/valid
areas, valid/source-supported fraction,
monthly source-supported/legal-county fraction, retrieval time, nullable original
publication time, distinct upstream modification time, publisher/dataset/vintage,
method/weight/geometry versions, labeled 24-hour early-morning-ending convention,
metadata revision and limitations. Exclude internal run, capture, revision and
artifact IDs; hashes; payloads; private URIs; credentials; and arbitrary JSON.
Do not forward candidate NDJSON wholesale. All rows carry one release identity.

Existing semantic governance requires semantic version `2.0.0` for the four
existing measure IDs with methodology `/2`. This aligns the approved verified
candidate; it does not add a product meaning or assert equivalence to v1.
Retain the historical v1 candidate and `/1` labels. Publication still requires
actual REVIEWED metadata and real review evidence, never invented approval.
Daily completeness is valid area / monthly source-supported area, threshold
0.95. Monthly spatial support is a separate fraction, not a daily missingness
test. Canonical county identity uses the existing 2022 asset; analysis geometry
uses 2025 TIGER/Line. PRCP unit is mm; temperatures are degree_Celsius. TAVG is
native NOAA TAVG. Preserve zero and negative temperatures. AK/HI remain null /
UNAVAILABLE. Partial or source-missing days remain null / MISSING with distinct
coverage statuses. This is descriptive weather context, not causal Lyme risk,
an annual aggregate, an ML admission decision, or a historical as-of claim.

## Least privilege and acceptance before publication

Prospective new objects are only the two named PRESENTATION views. Existing
V103 grants give the migration deployer SELECT on revisions; verify effective
view ownership and dependency rights through the intended connection before
claiming it can create the views. API reader needs existing database and
PRESENTATION schema USAGE plus SELECT on these two views only. Verify actual
reader role and existing grants first; no base revision/artifact grants, new
persistent grants, credentials or role escalation are authorized by this draft.

Required implementation tests: unchanged 3,144/44,016 fixed release counts;
extension included in immutable bundle hash; strict NOAA/TIGER source joins;
unreviewed or wrong-version metadata rejected; exact four approved climate
definitions accepted; unrelated derived measures still blocked; candidate
digest/membership mismatch rejected; no latest-run substitution; consumer
column allowlist; zero/negative/native-TAVG/unavailable live cases; separately
labeled partial/source-missing fixtures; release without extension and pointer
rollback expose no climate; intended API-reader SELECT and lineage audit.
Run repository Quality and deployment checks on the exact reviewed head.

The existing-release boundary is implementable; proceed with bounded offline
validator/view implementation and exact review. Target PROD capture/authority and intended-reader proof
are prerequisites, not permission errors to bypass. API #84 owner can consume
the named allowlist after those gates land; this DATA draft does not duplicate
API implementation or authorize deployment.
