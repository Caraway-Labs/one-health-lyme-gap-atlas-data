# Atlas semantic consumer v1

Status: Story #194 protected review candidate. Owner: Atlas data stewardship and engineering. Executable boundary: `semantic_consumer.py`; identity, metadata, mapping, lineage and compatibility authority remain #190–#195. API #52/#53/#55 own any later public discovery contract.

## Audience and fields

| Field group | INTERNAL | CONSUMER_SAFE | PUBLIC today |
| --- | --- | --- | --- |
| Source approval, run, artifact ID/hash, raw payload, physical relation/path, credentials, restricted source identifiers | Governed authority only | Excluded | Excluded |
| Indicator/measure IDs, semantic version, meaning signature, definition, type, unit, denominator, states, strata and applicability | Full #190/#191 | Allowlisted from validated reviewed metadata | Existing county API shape only; new discovery waits for API #52/#53 |
| Observation key/revision, value/state, native geography, period and strata | Full #190/#192 | Allowlisted after #190/#193 validation; source-only FIPS stays null | Existing county release response only |
| Publisher, source/dataset/version/vintage, method, freshness, quality/uncertainty, limitations | Full #191/#193 and governance joins | Safe metadata envelopes and exact source/version references | Existing release metadata only; expansion waits for API #52/#55 |
| Record lineage, evidence basis, derived result and release membership | Full #193 authority edges | `consumer_safe_lineage()` only, plus release ID/bundle when actual membership is validated | Existing public release provenance only; no new lineage resource |
| #158/#159 derived results | Governed internal result stores and contracts | Excluded pending exact reviewed exposure approval | Excluded |

`project_consumer()` validates the entire internal lineage against a caller-supplied authority snapshot before selecting fields. It requires `CONSUMER_SAFE` lineage and `CONSUMER_SAFE` or `PUBLIC` metadata classification. A non-fixture projection also requires `REVIEWED` steward metadata. Classification by itself never publishes to an HTTP API. The recursive restricted-value guard rejects unsafe output values and keys. The projection performs no query, storage mutation, approval, release publication or API call. Source approval and role access must be established by the caller; a synthetic authority snapshot is not such proof.

`contract_version` is `atlas-semantic-consumer-v1`. Exact metadata, observation, lineage and release revisions are carried so that a saved payload can be attributed to the same definitions and source snapshot. `canonical_consumer_json()` sorts keys and uses deterministic separators. A change to scientific meaning needs a reviewed #190 version/ID transition; a metadata edit needs an immutable #191 revision; a changed assertion needs a #190 revision; a changed publication set needs a new governed release. The consumer contract version changes under #195 governance when its own field meaning changes. Historical V071/V072 rows and the current 3,144-county, 14-slot release remain unchanged.

`page_consumer()` is bounded in-memory service discovery over already authorized projections. It supports optional exact indicator/measure IDs, nonnegative offset and a page limit of 1–100. Unknown IDs raise `KeyError`, invalid filters/pagination fail closed, and a known ID with no matching combined filter returns an empty page. It is not an HTTP pagination or access-policy decision; API #52 owns those semantics before #53/#55 are implemented.

## Current release and API handoff

The existing PROD `PRESENTATION.CURRENT_RELEASE_V`, `CURRENT_SOURCE_METADATA_V` and `CURRENT_COUNTY_ATLAS_V` feed the current FastAPI `/v1/atlas/metadata`, geometry, scores and county routes. They remain the PUBLIC contract. The new storage-neutral consumer projection does not rewrite those views, create a second current-release pointer, or make #158/#159 result stores public. #192 explicitly defers semantic adapters for the historical incidence-floor two-source lineage and state-unallocated state-native slot; this contract does not falsely recast either as a new county-native observation.

API Epic #51 targets broader public discovery, but #52 (resource/access/version policy) is open and blocks #53 and #55. A future API implementation should consume an approved data-side projection through its least-privilege presentation boundary, define HTTP error/cache/filter behavior in OpenAPI, and regenerate the Web Orval client in its own branch if OpenAPI changes. No API/Web contract or generated artifact changes in Story #194's data PR.

## Evidence limits

The `tests/test_semantic_consumer.py` inputs are synthetic #190–#193 fixtures. Fixture mode requires a synthetic `fixture-` source version and marks output `SYNTHETIC_FIXTURE`; it is never a publication approval. Local tests and hosted Quality are contract/container evidence. This change has no SQL, migration, connector, role, view or deployment behavior to validate in Snowflake. It establishes no DEV/PROD or live API response. Those evidence tiers remain separate in #194 completion reporting.
