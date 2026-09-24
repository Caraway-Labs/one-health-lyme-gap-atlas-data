# Story #190 current-state gap matrix

Audited protected `origin/main` at `e63c0c9aed93197819050d5b6b695a3afee32ea9` on 2026-09-24. No commits followed the supplied baseline. This matrix precedes the v1 domain contract. Classification describes the contract work, not a database migration or public publication.

| Target concept | Existing implementation | Current authoritative file/object | Classification | Gap | Story owner |
| --- | --- | --- | --- | --- | --- |
| Source identity | Manifest `source_key`, `source_id`, `resource_key`; governed source approval | `semantic_release.py` `SemanticSource`; `SEMANTIC_DATA_SOURCES` | DELIVERED / REUSE | Define cross-release identity relation | #190 |
| Dataset identity | Governed `dataset_id`, distinct from table | `SemanticSource`; `SEMANTIC_DATASETS` | EXTEND COMPATIBLY | Stable product identity rule beyond release | #190 |
| Indicator identity | Six release-local indicator IDs | `_insert_hierarchy`; `SEMANTIC_INDICATORS` | EXTEND COMPATIBLY | Stable semantic definition/version rule | #190 |
| Measure identity | Release-local measure IDs with unit/grain | `_insert_hierarchy`; `SEMANTIC_MEASURES` | EXTEND COMPATIBLY | Meaning fingerprint, denominator, allowed strata | #190 |
| Observation identity | County hash of release, measure, FIPS; canonical tick native key | `_observation_rows`; `tick_contract.canonical_observation_id` | NEW VERSIONED CONTRACT | General domain key and immutable revision independent of release | #190 |
| Source version | Pinned approved source version | `SemanticSource.data_source_version_id`; governed approval gate | DELIVERED / REUSE | Cross-shape reference rule | #190 |
| Source vintage | Manifest vintage; v2 exact-source tuple | `SemanticSource.vintage`; `surveillance-scientific-eligibility-v1.json` | EXTEND COMPATIBLY | Require explicit time meaning, not infer from version | #190 |
| Ingestion run | Pinned completed run | `SemanticSource.ingestion_run_id`; observation lineage | DELIVERED / REUSE | General mandatory provenance reference | #190 |
| Artifact | Pinned retained artifact and SHA | manifest; `SEMANTIC_OBSERVATIONS` | DELIVERED / REUSE | Safe reference only in consumer projection | #193 |
| Source record | Optional ID/hash in county release; native record IDs | `SEMANTIC_OBSERVATIONS`; canonical tick contract | EXTEND COMPATIBLY | Require record reference or bounded source-only reason | #190/#193 |
| Methodology/transformation version | Release method and row transformation; derived method/calculation versions | `SEMANTIC_RELEASES`; #158/#159 result contracts | EXTEND COMPATIBLY | Distinguish measure meaning from calculation revision | #190 |
| Release identity | Immutable release row, events, pointer | V071/V072; `semantic_release.py` | DELIVERED / REUSE | No change to publication | #190 |
| Observation revision | County release ID embeds release; derived result revision hash | `_observation_rows`; #158/#159 result contracts | NEW VERSIONED CONTRACT | Common identity/revision relationship without rewriting rows | #190 |
| Unit | Release measure `unit`; derived base units | `SEMANTIC_MEASURES`; #158 result contract | EXTEND COMPATIBLY | Exact definition and compatibility check | #190 |
| Denominator | Implicit in some release labels; explicit in M1/M2 | `_insert_hierarchy`; `infected-tick-metrics-v1.md` | NEW VERSIONED CONTRACT | Define typed denominator or explicit none | #190 |
| Geography identity | Five-digit canonical FIPS; native site/event IDs | `SEMANTIC_OBSERVATIONS`; canonical tick contract | EXTEND COMPATIBLY | Typed identity for non-county evidence | #190 |
| Geography grain | County release; `SITE_EVENT` canonical/derived | V071; canonical tick and #158 contracts | EXTEND COMPATIBLY | General applicability rules | #190 |
| Temporal semantics | Release window; canonical cumulative/period/point | `SEMANTIC_OBSERVATIONS`; canonical tick contract | EXTEND COMPATIBLY | Typed period identity and compatibility rules | #190 |
| Period | Human 2023, SVI ACS, RUCC 2023, CDC through-date | manifest; `_insert_hierarchy` | EXTEND COMPATIBLY | Do not infer period from display vintage | #190 |
| Optional scientific strata | Tick taxon/life stage/pathogen/method/testing scope | canonical tick; exact-source normalization registry | EXTEND COMPATIBLY | Approved dimension IDs and allowed sets | #190 |
| Reported vs derived | Canonical observations versus separate derived stores | canonical tick; V100–V102 | EXTEND COMPATIBLY | Shared origin rule and input references | #190 |
| Value state | Release `OBSERVED`/`ZERO`/`NULL`/`UNKNOWN`/`SUPPRESSED`; native/derived states | `_value_state`; canonical tick; #158/#159 | EXTEND COMPATIBLY | State/value consistency by shape | #190 |
| Quality | Source release quality state; analytical components | V071; `surveillance-quality-profile-v1.md` | DELIVERED / REUSE | Compose reference, no score | #157/#191 |
| Scientific eligibility | Exact-source attestation and tuple registry | `surveillance-scientific-eligibility-v1.*` | DELIVERED / REUSE | Keep source-specific proof | #159/#193 |
| Representativeness | `NOT_COUNTY_REPRESENTATIVE` site/event | canonical tick; #157/#159 | DELIVERED / REUSE | Enforce in domain shape | #190 |
| Uncertainty/limitations | Release limitations; quality propagation; derived reasons | `SEMANTIC_RELEASES`; `surveillance-quality-propagation-v1.md`; #158/#159 | EXTEND COMPATIBLY | Reusable metadata content and safe projection | #191 |
| Evidence basis | v2 immutable result revisions distinguish synthetic/source-backed | `surveillance-coverage-result-v2.md`; `surveillance-priority-result-v2.md` | DELIVERED / REUSE | Common optional reference, never infer proof level | #190/#193 |
| Safe lineage | County observation anchors; derived input IDs and safe IDs | V071/V072; #158/#159 result contracts | EXTEND COMPATIBLY | Multi-input lineage and consumer projection | #193 |
| Immutable history | Candidate rows, event log, separate append-only V100–V102 stores | V071, V100–V102 | DELIVERED / REUSE | No rewriting historical IDs/rows | #190 |
| Public/consumer representation | Three API-facing current-release views | V072 `CURRENT_*_V` | DEFERRED / OUT OF SCOPE | Broader safe machine-readable projection | #194 |

The current published release remains 3,144 counties × 14 observations; `PRESENTATION.SEMANTIC_OBSERVATIONS` is not a general site/event result store. V100–V102 remain separate DEV-only result stores. The v1 domain contract describes relationships across these shapes without inserting new rows or changing the pointer.
