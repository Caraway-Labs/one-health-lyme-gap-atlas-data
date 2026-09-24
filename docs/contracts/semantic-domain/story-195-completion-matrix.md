# Story #195 completion matrix

| #195 acceptance criterion | Governance artifact/code | Test/evidence | Status |
| --- | --- | --- | --- |
| Executable IDs/cardinalities, types, units, denominators, geography/time/strata, states, metadata, lineage, evidence and transitions | Existing #190–#193 validators composed by `semantic_governance.py` | `test_semantic_domain.py`, `test_semantic_metadata.py`, `test_semantic_lineage.py`, `test_semantic_source_mappings.py`, `test_semantic_governance.py` | COMPLETE for fixture/code contracts |
| Immutable published county baseline | `county-release-v1.json`; governance contract | `test_frozen_county_release_slots_and_meaning` | COMPLETE as contract fixture; no PROD audit claim |
| Multi-shape county/site-event/derived/source-only, incompatible denominators, states, duplicate/orphan cases | Existing #190–#193 fixtures plus #195 transition cases | Normal pytest suite, focused governance suite | COMPLETE for synthetic fixtures |
| Generated checks from governed registries | #192 registry, frozen registry snapshot and existing tick registry tests; #195 mapping parameterization | One generated identity/vintage case per registry entry; exact registry baseline check; normal suite exercises tick registry | COMPLETE for current registries |
| Changed connector/procedure/role/storage behavior in real Snowflake | No such behavior changed | No DB integration asserted | NOT APPLICABLE |
| Candidate build/failure, pointer, retry, publication prerequisites, immutable history, #194 compatibility | Existing release validator, frozen current output contract, and bounded transaction fakes | `test_semantic_release.py`, `test_publish_semantic_release_workflow.py`, `test_candidate_build_rolls_back_and_retry_keeps_pointer`, `test_existing_release_identity_blocks_candidate_rebuild`, `test_valid_candidate_publication_then_repeat_is_blocked`, #195 release baseline | COMPLETE for code/fixture boundary; #194 future output remains #194 |
| CI separates fixture/integration/protected/live evidence | Normal Quality pytest job; governance contract evidence section | Hosted Quality after updated PR | PENDING refreshed hosted Quality |
| Versioning/deprecation and owning remediation path | `atlas-semantic-governance-v1.md`, `semantic_governance.py` | Transition and removal tests | COMPLETE for #195 |
| No weaker permissions or history/Alpha/restricted access | Python/contracts/tests only | Diff review; no migration, workflow or API edits | PENDING final diff review |

Story #194 owns machine-readable consumer/public representation, API and generated-client changes, live consumer tests, and migration execution. No #194 implementation is included here.

## Required adversarial cases

| Case | Executable evidence |
| --- | --- |
| 1 label-only metadata | `test_label_only_metadata_revision_is_compatible` |
| 2 definition without new semantic version | `test_breaking_measure_requires_major_version`; `test_label_only_metadata_revision_is_compatible` |
| 3 unit change | `test_breaking_measure_requires_major_version` |
| 4 denominator change | `test_breaking_measure_requires_major_version` |
| 5 county to site/event | `test_breaking_measure_requires_major_version` |
| 6 period to point-in-time | `test_breaking_measure_requires_major_version` |
| 7 optional stratum addition | `test_label_and_optional_stratum_transitions` |
| 8 unknown canonical stratum | `test_label_and_optional_stratum_transitions`; `test_neon_strata_fail_closed` |
| 9 exact-source mapping removed | `test_mapping_removal_and_foreign_source_fail` |
| 10 foreign-source mapping | `test_mapping_removal_and_foreign_source_fail`; `test_composed_mapping_references_and_exact_source` |
| 11 source vintage change | `test_governed_mapping_identity_is_stable`; `test_mapping_registry_requires_explicit_baseline_review` |
| 12 evidence-basis change | `test_evidence_basis_changes_revision_not_scientific_scope`; `test_rejects_derived_input_and_basis_mismatch` |
| 13 reordered derived inputs | `test_ordering_and_duplicate_immutable_identity` |
| 14 changed derived inputs | `test_revision_and_observation_keys_track_different_changes`; `test_rejects_derived_input_and_basis_mismatch` |
| 15 missing metadata revision | `test_lineage_and_result_revisions_are_immutable`; `test_missing_metadata_and_lineage_fail_closed` |
| 16 missing lineage ID | `test_composed_mapping_references_and_exact_source` |
| 17 source-only evidence with county FIPS | `test_source_only_never_becomes_canonical_county`; `test_source_only_cannot_become_county` |
| 18 site/event representativeness removed | `test_neon_site_event_representativeness_cannot_disappear` |
| 19 incidence floor reduced to one source | `test_incidence_floor_uses_human_count_and_svi_population` |
| 20 state-unallocated treated as county-native | `test_state_unallocated_is_not_county_native` |
| 21 release slot removed | `test_candidate_cannot_change_old_release_meaning` |
| 22 changed 14-slot meaning under same schema | `test_frozen_county_release_slots_and_meaning` |
