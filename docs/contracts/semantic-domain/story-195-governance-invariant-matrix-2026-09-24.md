# Story #195 semantic governance invariant matrix

Baseline: `origin/main` `058d169d51bbfa591b10a30da2141cb599373f5c` (the #192 merge; no later commits). Authority: `atlas-semantic-domain-v1`, ADR 0035, `atlas-semantic-metadata-v1`, `atlas-semantic-lineage-v1`, `atlas-semantic-source-mappings-v1`, and the existing semantic-release and #157–#159 contracts. This is a fixture/code audit, not live source or PROD evidence. `ALREADY ENFORCED` describes the existing validator at its own boundary; composition and future-version checks remain #195 work.

| Invariant | Authority | Current enforcement | Compatibility rule | Failure behavior | Gap | #195 action |
| --- | --- | --- | --- | --- | --- | --- |
| Source identity | source mappings; lineage | `load_mapping_registry`, `validate_lineage`; mapper | Exact approved source tuple remains pinned | Mapping/lineage error | NEEDS COMPOSITION | Compare exact tuples and cross-contract references |
| Dataset identity | domain; mappings | `validate_observation`, mapper | Stable product ID; changed product is new scope | Domain/mapping error | NEEDS COMPOSITION | Govern mapping transition |
| Indicator identity | domain; metadata | `validate_measures`, `validate_metadata` | Stable machine ID | Domain/metadata error | NEEDS COMPOSITION | Compare registry definitions |
| Measure identity | domain; metadata | `validate_measures`, `validate_metadata` | Meaning change requires new semantic version | Domain/metadata error | NEEDS NEW CHECK | Cross-version comparison and baseline gate |
| Semantic version | domain; ADR 0035 | Definition validation; `meaning_signature` | No changed meaning at same version | Domain error | NEEDS NEW CHECK | Executable transition classification |
| Observation identity | domain | `observation_key`, `validate_domain` | Changed scope/inputs gives new key | Domain error | NEEDS COMPOSITION | Compare immutable revisions |
| Immutable revision identity | domain; #158/#159 | `revision_id`, lineage result joins | Changed payload/evidence gives new revision | Domain/lineage error | NEEDS COMPOSITION | Transition tests and history protection |
| Metadata revision | metadata | `validate_metadata_revisions` | Increment for compatible explanation; no old-revision edit | Metadata error | NEEDS COMPOSITION | Cross-version metadata matrix |
| Lineage identity | lineage | `lineage_id`, `validate_lineages` | Changed edge/proof/method gives new ID | Lineage error | NEEDS COMPOSITION | Transition and reference checks |
| Mapping identity | source mappings | Registry unique IDs; mapper | Removal requires explicit deprecation | Mapping error | NEEDS NEW CHECK | Compare pinned registry baseline |
| Release identity | semantic release V071/V072 | Manifest/bundle and publication guards | New publication gets new ID/bundle | `SemanticReleaseBlocked` | NEEDS COMPOSITION | Candidate versus baseline comparison |
| Unit | domain; metadata; mappings | Definition, metadata, mapper checks | Changed semantics needs new measure version | Domain/metadata/mapping error | NEEDS COMPOSITION | Explicit unit transition reason |
| Denominator | domain; metadata; #158/#159 | Definition, metadata, mapper checks | Changed denominator needs new version | Domain/metadata/mapping error | NEEDS COMPOSITION | Explicit denominator transition reason |
| Numeric/categorical type | domain | `validate_measures`, `validate_observation` | Type change is breaking | Domain error | NEEDS COMPOSITION | Generated allowed-type tests |
| Value-state compatibility | domain; #158/#159 | `validate_observation`; result validators | Null/zero/unknown/suppressed/unavailable never coerce | Domain/result error | NEEDS COMPOSITION | Registry-driven state tests |
| County grain | domain; release | FIPS/row validation and release builder | County FIPS only for county-native assertion | Domain/release error | NEEDS COMPOSITION | County transition and baseline checks |
| Site/event grain | domain; NEON canonical | Native IDs and representativeness check | No automatic county aggregation | Domain/canonical error | NEEDS COMPOSITION | NEON adversarial regressions |
| Source-only/unresolved geography | domain; #159 | Null FIPS and `UNKNOWN` validation | Cannot imply completeness or cohort | Domain/eligibility error | NEEDS COMPOSITION | Cross-contract source-only regressions |
| Representativeness | domain; metadata; #157/#159 | `NOT_COUNTY_REPRESENTATIVE` checks | Changed claim is breaking | Domain/metadata/result error | NEEDS COMPOSITION | Native site/event regression |
| Cumulative time | domain; county status | `_scope`, mapping rule | Cannot become period/event silently | Domain/mapping error | NEEDS COMPOSITION | Time transition tests |
| Period time | domain; release | `_scope`, release dates | Cannot become point-in-time silently | Domain/mapping error | NEEDS COMPOSITION | Time transition tests |
| Point-in-time/event time | domain; NEON | `_scope`, canonical adapter | Native event date retained | Domain/canonical error | NEEDS COMPOSITION | Generated time cases |
| Taxon stratum | domain; tick registry | `_STRATA`, exact normalization | New canonical ID needs governed rule | Domain/mapping error | NEEDS COMPOSITION | Generate registry tests |
| Life-stage stratum | domain; tick registry | `_STRATA`, exact normalization | Same | Domain/mapping error | NEEDS COMPOSITION | Generate registry tests |
| Pathogen-target stratum | domain; tick registry | `_STRATA`, exact normalization | Same | Domain/mapping error | NEEDS COMPOSITION | Generate registry tests |
| Collection-method stratum | domain; tick registry | `_STRATA`, exact normalization | Same | Domain/mapping error | NEEDS COMPOSITION | Generate registry tests |
| Testing-scope stratum | domain; tick registry | `_STRATA`, exact normalization | Same | Domain/mapping error | NEEDS COMPOSITION | Generate registry tests |
| Source version | mappings; lineage | Exact source/version joins | Changed source requires revision and eligibility review | Mapping/lineage error | NEEDS COMPOSITION | Transition tests |
| Vintage | mappings; metadata; lineage | Exact vintage checks | New vintage is new pinned input | Mapping/metadata/lineage error | NEEDS COMPOSITION | Transition tests |
| Run | lineage; release | Authority joins and source gate | New run is new provenance revision | Lineage/release error | ALREADY ENFORCED | Retain in composed validation |
| Artifact | lineage; release | ID/hash joins | New artifact is new provenance revision | Lineage/release error | ALREADY ENFORCED | Retain in composed validation |
| Record | lineage; domain | Record identity/hash joins | New record changes observation identity/revision | Lineage/domain error | ALREADY ENFORCED | Retain in composed validation |
| Normalization/eligibility proof | mappings; lineage; #159 | Exact proof joins and tick normalization | Changed proof requires new lineage/revision | Mapping/lineage error | NEEDS COMPOSITION | Generated proof regressions |
| Transformation/method | domain; lineage; #158/#159 | Versioned method/result joins | Changed calculation needs new result revision | Domain/lineage error | NEEDS COMPOSITION | Transition tests |
| Evidence basis | #158/#159; lineage | Owning allowlists and joins | Change is distinct immutable result | Result/lineage error | NEEDS COMPOSITION | Generated basis tests |
| Definition | domain; metadata | Meaning signature and metadata revision checks | Scientific change needs semantic version | Domain/metadata error | NEEDS NEW CHECK | Cross-version definition comparison |
| Applicability | metadata; domain | Grain/time/strata agreement | Meaning-bearing change needs semantic version | Metadata error | NEEDS COMPOSITION | Metadata transition tests |
| Freshness | metadata; #157 | Explicit state/date checks | Revision, never inferred staleness | Metadata error | ALREADY ENFORCED | Retain in composed validation |
| Quality | #157; metadata; #158/#159 | Contract references and result validators | Preserve owning reason codes and evidence | Metadata/result error | NEEDS COMPOSITION | Cross-reference tests |
| Limitations | metadata; #157–#159 | Typed limitations and safe projection | Compatible detail may revise metadata; interpretation change reviewed | Metadata error | NEEDS COMPOSITION | Metadata transition tests |
| Authority/review state | metadata; source governance | Review and source approval checks | Pending cannot authorize live mapping | Metadata/mapping error | ALREADY ENFORCED | Retain in composed validation |
| Safe visibility | metadata; lineage | Safe-field guards | Classification does not authorize publication | Metadata/lineage error | DEFERRED / #194 | Check only existing safe contract; no consumer exposure |
| 3,144-county release | semantic release contract | Builder `EXPECTED_COUNTIES` | Candidate must retain governed boundary | Release blocked | NEEDS COMPOSITION | Commit immutable baseline fixture |
| Fourteen physical slots | semantic release V071/V072 | Builder and tests | Slot meaning cannot change under same schema | Release blocked/test failure | NEEDS NEW CHECK | Fixture and schema regression gate |
| Release pointer | semantic release | Publish transaction and tests | Invalid candidate cannot replace pointer | Release blocked | ALREADY ENFORCED | Reuse tests; assert failure behavior |
| Immutable historical releases | semantic release V071/V072 | Candidate insert/publish guards | Never edit old rows; new release ID | Release blocked | ALREADY ENFORCED | Reuse idempotency/history tests |
| Public views | V072; #194 boundary | Current view SQL and API compatibility tests | Preserve current shape; new exposure is #194 | Test failure | DEFERRED / #194 | Check current schema only, no new output |

Special historical boundaries: incidence floor requires human case count and SVI population; the physical historical row is human-pinned, so a one-source #190 adapter must fail pending complete lineage. State-unallocated counts retain state meaning even inside the county release and must not become county-native #190 observations. Both are #195 regression checks, not #192 mapping rewrites.
