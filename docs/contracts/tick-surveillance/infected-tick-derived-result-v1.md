# Infected-tick derived result v1

Status: Internal DEV output contract for Story #169
Owner: Atlas data stewardship and engineering
Contract version: `infected-tick-derived-result-v1`

## Gap and placement decision

The existing canonical tick contract and `GOVERNANCE` / `RAW` / `STAGING` /
`CONFORMED` tables describe source observations. A calculated metric is not a
source observation and cannot be written there. The present
`PRESENTATION.SEMANTIC_OBSERVATIONS` table has a nullable FIPS field, but its
builder, fixed five-source manifest, 3,144-county / 14-observation invariants,
release pointer, and current API views are county oriented. Inserting SITE_EVENT
metrics would change the meaning and counts of an already published release.
It does not model arbitrary native strata, the #165 component profile, #166
limitations, or distinct unavailable reasons for this metric envelope.

Story #169 therefore adds one focused, DEV-only
`PRESENTATION.INFECTED_TICK_DERIVED_RESULTS` table for immutable, consumer-safe
derived results. It is not a generalized semantic observation table or an
indicator registry. The table has no current-release pointer and no API or web
read grant. `#190`–`#194` own broader ontology, metadata, cross-domain mapping,
lineage, and public machine-readable access. The county release continues to
use its existing storage and views without any row, count, or meaning change.

## Result shape

`serialize_infected_tick_result` consumes the #168 result envelope. It accepts
only `OBSERVED_PATHOGEN_PREVALENCE` and
`EFFORT_NORMALIZED_COLLECTION_DENSITY`, methodology
`infected-tick-metrics-v1`, calculation `infected-tick-calculation-v1`, and
native `SITE_EVENT` grain. Its allowlisted document includes:

- `metric_identity`, `metric_id`, methodology and calculation versions,
  `result_id`, and `result_revision`;
- `NUMERIC` or `UNAVAILABLE`, base numeric value (including valid zero) or
  explicit null plus deterministic unavailable reasons, numerator, denominator,
  and base unit (`proportion` or `ticks_per_square_metre`);
- optional governed `ticks_per_hectare` presentation conversion with the
  reviewed registry rule, without replacing the base density;
- source publisher/dataset/release, source site/plot, event/sample/subsample/
  batch, source coordinates/CRS/uncertainty, date, taxon, life stage, pathogen
  or collection method, and M1 per-input source testing IDs where supplied;
- a contextual county mapping only where reported or derived, always with
  `NOT_COUNTY_REPRESENTATIVE`; unmapped or ambiguous sites have null FIPS;
- exact canonical input IDs, safe source dataset/version/record/run/retrieval
  references, canonical and normalization versions/rule IDs, #165 quality
  components, #166 inherited and added limitations/reason codes;
- an explicit calculation evidence basis and separate historical-ingestion
  reference. Current-code source-backed replay remains `EVIDENCE_LIMITED`.

M2's date is collection date. M1's date is tested date. Testing-method details
that are not present in the #168 canonical envelope cannot be invented;
source testing IDs and exact canonical input IDs retain the reported scope.
The output makes no county observation or aggregate.
An `UNAVAILABLE` result retains null site, event, date, or safe lineage fields
when those missing facts caused abstention; the reason codes explain the gap.
Numeric results require those facts and a positive denominator.

## Identity, revision, and duplicate behavior

`metric_identity` is the #168 deterministic identity over method, source,
site/event stratum, and exact canonical inputs. `result_revision` is SHA-256
of the safe scientific payload, including calculation version, state, value,
denominators, lineage, quality, and limitations. `result_id` prefixes that
digest. Identical recalculation has the same ID. Changed input IDs, source
release, source record/artifact revision, method, calculation version, or
scientific payload gets a distinct revision ID when it is supported by the
contract. An unreviewed methodology or calculation version fails closed at
serialization; a later reviewed contract may admit it as a new identity and
revision. The approved #168 calculator may mark an unsupported source revision
unavailable; storage never resolves it.
Optional presentation conversion and evidence annotations are not part of
scientific identity. Once one document has been staged, replaying identical
bytes is a no-op; attempting to reuse that ID with any changed stored payload
fails closed. History is never updated or deleted.

`stage_infected_tick_result` writes only a validated safe document and reads
back its payload digest. The intended single runtime writer is
`OH_LYME_DEV_RUNTIME`, with `SELECT, INSERT` only. `OH_LYME_DEV_READ` has
`SELECT` for bounded inspection. Snowflake standard-table primary keys are
informational, so a caller must serialize writers for this table; the writer
checks for duplicate/conflicting rows before and after its MERGE. A detected
conflict fails rather than rewriting either result. No PROD migration is
scheduled, and staging confers no publication approval.

## Evidence and interpretation boundary

`SYNTHETIC_FIXTURE` is the only basis for fixture integration. The separate
`CURRENT_CODE_CI_TESTED_SOURCE_REPLAY_LIMITED` basis describes calculation
test/CI evidence, without claiming live replay. Historical #162 governed DEV
ingestion run `ea8db548-62b0-4632-84ca-02eee97ead41` is marked as
`SEPARATE_162_EVIDENCE_NOT_RESULT_LINEAGE` for both bases, never as a current
result's scientific input lineage or current-code M2 replay proof.
Current NEON M1 remains `UNAVAILABLE` without resolved life stage; compliant
synthetic M1 demonstrates the implemented formula. A valid zero describes only
the tested or collected stratum with its positive denominator. Neither metric
establishes county coverage, population prevalence, human risk, or method
comparability.

The projection excludes artifact IDs/URIs, signed URLs, raw payloads, object
store locations, and credentials. It rejects URL and credential-like content
even if placed in an allowed field. This is an internal safe serialization
contract, not authorization for external release.
